"""거래량/거래대금 계열 특징 전수 스크리닝 (탐색 구간 전용).

규칙:
 - 수익률/비용/연속성 계산은 전부 lib.py 를 통해서만 한다.
 - lib.fwd_returns(d,'disc') 만 호출한다. 'hold' 는 봉인 구간이라 절대 열지 않는다.
 - 격자는 먼저 전부 정의하고(아래 build_features), 결과를 보고 조정하지 않는다.

출력: research/upbit5m/result_volume.md
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import lib

BAR = lib.BAR_MS
LIQ_MIN = 1e8            # 24h 거래대금 하한 1억원 (유동성 필터 버전)
MAX_DENSITY = 0.10       # 전체(평가가능) 봉의 10% 이상 발동 = 신호 아님
MIN_N = 500


def roll_med(x, n):
    return pd.Series(x).rolling(n, min_periods=n).median().to_numpy()


def roll_mean(x, n):
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def roll_sum(x, n):
    return pd.Series(x).rolling(n, min_periods=n).sum().to_numpy()


def roll_max(x, n):
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def win_contig(t, n):
    """i-n+1 .. i 구간이 시간축에서 결측 없이 연속인가."""
    out = np.zeros(len(t), bool)
    if len(t) >= n:
        out[n - 1:] = (t[n - 1:] - t[:len(t) - n + 1]) == (n - 1) * BAR
    return out


def safe_div(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        r = a / b
    r[~np.isfinite(r)] = np.nan
    return r


def build_features(d):
    """사전 확정 격자. 반환: (이름 -> bool 배열), liq(bool), n"""
    t, o, c, v, qv = d['t'], d['o'], d['c'], d['v'], d['qv']
    n = len(t)
    F = {}

    # 창 연속성
    CG = {N: win_contig(t, N) for N in (12, 48, 288, 864)}

    # ---- 급증배수 (거래량 / 거래대금) ----
    for N in (12, 48, 288, 864):
        mv = roll_med(v, N)
        mq = roll_med(qv, N)
        rv = safe_div(v, np.where(mv > 0, mv, np.nan))
        rq = safe_div(qv, np.where(mq > 0, mq, np.nan))
        rv = np.where(CG[N], rv, np.nan)
        rq = np.where(CG[N], rq, np.nan)
        if N == 48:
            rq48 = rq
        if N == 288:
            rq288 = rq
        for X in (3, 5, 10, 20):
            F[f'vspike{N}>={X}'] = np.nan_to_num(rv, nan=-1) >= X
            F[f'qspike{N}>={X}'] = np.nan_to_num(rq, nan=-1) >= X

    # ---- 24h 거래대금 절대 수준 (288봉 합) ----
    qv24 = np.where(CG[288], roll_sum(qv, 288), np.nan)
    q = np.nan_to_num(qv24, nan=-1)
    ok24 = np.isfinite(qv24)
    F['qv24h<1e8'] = ok24 & (q < 1e8)
    F['qv24h_1e8~1e9'] = ok24 & (q >= 1e8) & (q < 1e9)
    F['qv24h_1e9~1e10'] = ok24 & (q >= 1e9) & (q < 1e10)
    F['qv24h>=1e10'] = ok24 & (q >= 1e10)
    liq = ok24 & (q >= LIQ_MIN)

    # ---- 거래량 추세: 최근 S봉 평균 / 직전 L봉 평균 ----
    for (S, L) in ((12, 288), (48, 864), (12, 864)):
        ms = roll_mean(v, S)
        ml_all = roll_mean(v, L)
        ml = np.full(n, np.nan)
        ml[S:] = ml_all[:n - S]                      # 직전(겹치지 않는) L봉
        cg = win_contig(t, S + L)
        tr = safe_div(ms, np.where(ml > 0, ml, np.nan))
        tr = np.where(cg, tr, np.nan)
        z = np.nan_to_num(tr, nan=-1)
        for X in (2, 3, 5):
            F[f'vtrend{S}/{L}>={X}'] = z >= X
        for X in (0.5, 0.3):
            F[f'vtrend{S}/{L}<={X}'] = np.isfinite(tr) & (z <= X)

    # ---- 가격-거래량 조합 ----
    bar_up = c > o
    bar_dn = c < o
    for N, rq in ((48, rq48), (288, rq288)):
        z = np.nan_to_num(rq, nan=-1)
        for X in (3, 5, 10):
            F[f'qspike{N}>={X}&양봉'] = (z >= X) & bar_up
            F[f'qspike{N}>={X}&음봉'] = (z >= X) & bar_dn

    ret12 = np.full(n, np.nan)
    ret12[12:] = (c[12:] / c[:n - 12] - 1) * 100
    ret12 = np.where(win_contig(t, 13), ret12, np.nan)
    ret48 = np.full(n, np.nan)
    ret48[48:] = (c[48:] / c[:n - 48] - 1) * 100
    ret48 = np.where(win_contig(t, 49), ret48, np.nan)
    z288 = np.nan_to_num(rq288, nan=-1)
    for X in (3, 5, 10):
        F[f'qspike288>={X}&ret12>+3%'] = (z288 >= X) & (np.nan_to_num(ret12, nan=0) > 3)
        F[f'qspike288>={X}&ret12<-3%'] = (z288 >= X) & (np.nan_to_num(ret12, nan=0) < -3)

    # ---- 거래량 없는 가격 이동 ----
    quiet48 = np.isfinite(rq48) & (np.nan_to_num(rq48, nan=9e9) <= 1.2)
    quiet288 = np.isfinite(rq288) & (np.nan_to_num(rq288, nan=9e9) <= 1.2)
    F['조용ret12>+3%'] = quiet48 & (np.nan_to_num(ret12, nan=0) > 3)
    F['조용ret12<-3%'] = quiet48 & (np.nan_to_num(ret12, nan=0) < -3)
    F['조용ret48>+5%'] = quiet288 & (np.nan_to_num(ret48, nan=0) > 5)
    F['조용ret48<-5%'] = quiet288 & (np.nan_to_num(ret48, nan=0) < -5)

    # ---- 봉당 평균체결액 qv/v ----
    ats = safe_div(qv, np.where(v > 0, v, np.nan))
    for N in (48, 288):
        m = roll_med(ats, N)
        r = safe_div(ats, np.where(m > 0, m, np.nan))
        r = np.where(CG[N], r, np.nan)
        z = np.nan_to_num(r, nan=-1)
        for X in (1.5, 2, 3):
            F[f'ats{N}>={X}'] = z >= X
        F[f'ats{N}<=0.5'] = np.isfinite(r) & (z <= 0.5)

    # ---- 거래대금 집중도: 최근 N봉 중 최대 1봉 비중 ----
    for N in (48, 288):
        mx = roll_max(qv, N)
        sm = roll_sum(qv, N)
        r = safe_div(mx, np.where(sm > 0, sm, np.nan))
        r = np.where(CG[N], r, np.nan)
        z = np.nan_to_num(r, nan=-1)
        for X in (0.3, 0.5, 0.7):
            F[f'집중도{N}>={X}'] = z >= X

    return F, liq, n


def main():
    syms = lib.symbols()
    feat_parts, liq_parts, ret_parts, ts_parts, mask_parts = {}, [], {h: [] for h in lib.HORIZONS}, [], []
    sym_parts = []
    names = None

    for i, s in enumerate(syms):
        d = lib.load(s)
        mask, rets = lib.fwd_returns(d, 'disc')       # 탐색 구간만. 'hold' 는 열지 않는다.
        F, liq, n = build_features(d)
        if names is None:
            names = list(F.keys())
            feat_parts = {k: [] for k in names}
        for k in names:
            feat_parts[k].append(F[k])
        liq_parts.append(liq)
        mask_parts.append(mask)
        ts_parts.append(d['t'])
        sym_parts.append(np.full(n, i, np.int16))
        for h in lib.HORIZONS:
            ret_parts[h].append(rets[h].astype(np.float32))
        del d, F, rets
        if (i + 1) % 40 == 0:
            print(f'  loaded {i+1}/{len(syms)}', flush=True)

    ts = np.concatenate(ts_parts); del ts_parts
    base = np.concatenate(mask_parts); del mask_parts
    liq = np.concatenate(liq_parts); del liq_parts
    symid = np.concatenate(sym_parts); del sym_parts
    R = {h: np.concatenate(ret_parts[h]).astype(np.float64) for h in lib.HORIZONS}
    del ret_parts
    feats = {}
    for k in names:
        feats[k] = np.concatenate(feat_parts[k])
        feat_parts[k] = None
    print(f'총 봉 {len(ts):,} / 탐색구간 {int(base.sum()):,} / 특징 {len(names)}개', flush=True)

    # 지평별 평가가능 봉 수 (밀도 분모)
    elig = {h: base & np.isfinite(R[h]) for h in lib.HORIZONS}
    elig_liq = {h: elig[h] & liq for h in lib.HORIZONS}

    rows = []
    ntest = 0
    for k in names:
        f = feats[k]
        for liqname, EL in (('전체', elig), ('24h거래대금>=1억', elig_liq)):
            for h in lib.HORIZONS:
                sig = f & EL[h]
                nsig = int(sig.sum())
                den = int(EL[h].sum())
                dens = nsig / den if den else 1.0
                for dirn in ('롱', '숏'):
                    ntest += 1
                    if dens > MAX_DENSITY or nsig < MIN_N:
                        continue
                    r = R[h] if dirn == '롱' else lib.short_of(R[h])
                    st = lib.evaluate(sig, r, ts, min_n=MIN_N)
                    if not st['ok']:
                        continue
                    nsym = int(len(np.unique(symid[sig & np.isfinite(r)])))
                    rows.append(dict(feat=k, liq=liqname, dirn=dirn, hz=h, dens=dens, nsym=nsym, **st))
    print(f'검정한 총 조합 수 = {ntest}', flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sweep_volume_all.csv'),
              index=False, encoding='utf-8')

    liqrate = float(liq[elig['24h']].mean())
    out = [
        '# 거래량/거래대금 계열 특징 스크리닝 결과 (탐색 구간)',
        '',
        f'- 데이터: 업비트 원화 5분봉 {len(syms)}종목, 탐색 구간(`disc`, SPLIT 이전) 봉 {int(base.sum()):,}개',
        '- 계산은 전부 `lib.py` 경유. `lib.fwd_returns(d, "disc")` 만 호출 (봉인 구간 `hold` 미개봉)',
        f'- **검정한 총 조합 수 = {ntest}** '
        f'(특징 {len(names)}개 x 유동성필터 2 x 지평 5 x 방향 2)',
        f'- 필터: 발동 밀도 <= {MAX_DENSITY:.0%}, 표본 >= {MIN_N}건, 평균 > 0, 부호유지 = True',
        f'- 24h 거래대금 >= 1억원 통과 봉 비율(24h 지평 평가가능 봉 기준) = {liqrate*100:.1f}% '
        f'— 하한이 낮아 표본이 거의 줄지 않는다. 두 표의 차이는 주로 밀도 분모 변화에서 온다',
        '',
        '> 주의 1: `qv/v` 는 봉 VWAP(가격)이다. 체결 건수 정보가 없어 "봉당 평균체결액"의 대리지표가 '
        '되지 못한다. 따라서 `atsN` 계열은 사실상 **가격이 최근 N봉 중앙 VWAP 대비 몇 배인가**(급등 수준) '
        '이며 거래량 특징이 아니다. 표에 남기되 그렇게 읽어야 한다.',
        '> 주의 2: 5분봉 신호는 시간적으로 겹친다(24h/48h 지평은 288/576봉 중복). n 은 독립 표본 수가 아니다.',
        '> 주의 3: 업비트 원화는 현물이라 숏 실행 경로가 없다(사전등록 §9.5). 숏 결과는 다른 거래소 비용이 '
        '반영되지 않은 값이다.',
        '',
    ]
    for liqname in ('전체', '24h거래대금>=1억'):
        sub = df[(df.liq == liqname) & (df['mean'] > 0) & (df.sign_stable)].sort_values('mean', ascending=False).head(15)
        out.append(f'## 유동성 조건: {liqname}')
        out.append('')
        if len(sub) == 0:
            out.append('**조건 충족 0개**')
            out.append('')
            continue
        out.append('| 특징 정의(재현 가능) | 방향 | 지평 | n | 평균% | 중앙% | 승률% | 최대기여일제외 평균% | 부호유지 | 발동밀도% | 일수 | 종목수 |')
        out.append('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for _, r in sub.iterrows():
            out.append(f"| `{r.feat}` | {r.dirn} | {r.hz} | {r.n} | {r['mean']:.3f} | {r['median']:.3f} | "
                       f"{r.win:.1f} | {r.mean_ex_topday:.3f} | {r.sign_stable} | {r.dens*100:.2f} | "
                       f"{r.ndays} | {r.nsym} |")
        out.append('')

    # 참고: 거래대금 절대 수준(유동성) 구간별 성적 — 표 조건과 무관하게 그대로 싣는다
    lv = df[(df.liq == '전체') & (df.feat.str.startswith('qv24h'))]
    out.append('## 참고 — 24h 거래대금 절대 수준 구간별 (롱 기준, 필터 무관하게 전부 표기)')
    out.append('')
    out.append('| 구간 | 지평 | n | 롱 평균% | 발동밀도% |')
    out.append('|---|---|---|---|---|')
    for _, r in lv[lv.dirn == '롱'].iterrows():
        out.append(f"| `{r.feat}` | {r.hz} | {r.n} | {r['mean']:.3f} | {r.dens*100:.2f} |")
    out.append('')
    out.append('`qv24h>=1e10` 구간은 발동 밀도가 10%를 넘어(신호 아님) 표에서 빠졌다. '
               '유동성 수준 자체는 방향성 신호를 주지 않는다.')
    out.append('')

    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result_volume.md')
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    print('\n'.join(out))


if __name__ == '__main__':
    main()
