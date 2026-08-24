# -*- coding: utf-8 -*-
"""모멘텀/수익률 계열 특징 격자 탐색 (업비트 원화 5분봉, 탐색 구간 'disc'만)

규칙
 - 수익률/비용/구간 연속성 계산은 전부 research/upbit5m/lib.py 가 한다.
 - lib.fwd_returns(d,'disc') 만 호출한다. 'hold' 는 호출하지 않는다.
 - 격자는 결과를 보기 전에 아래 GRID 섹션에 전부 확정해두고, 그대로 전수 실행한다.

특징 계산 규약(재현용)
 - 되돌아보기 길이 L 은 '봉 수'가 아니라 '시간'으로 잡는다. 업비트 5분봉은 거래가 없으면
   봉 자체가 빠져서(전체 봉 전이의 22%가 결측) 인덱스 기준 L봉은 시간이 제각각이다.
   j(i) = t[j] <= t[i] - L*300000 인 마지막 인덱스,  유효조건: j>=0 이고
   t[i]-t[j] <= 1.5 * L * 300000  (허용 늘어짐 1.5배). 조건 불만족이면 NaN.
 - R_L(i) = (c[i]/c[j(i)] - 1) * 100   (단위: %, 원시 가격 수익률. 비용 미차감.
   이건 '특징'이지 성과가 아니다. 성과 수익률은 전부 lib.fwd_returns 가 준 값만 쓴다.)
 - Z_L(i) = (R_L(i) - mean) / std,  mean/std 는 R_L 의 뒤쪽 2016봉(인덱스 기준) 이동창,
   최소 관측 500. 현재 봉 포함(미래 미사용).
 - 연속 상승/하락 봉수: cond(i) = (t[i]-t[i-1]==300000) and (c[i]>c[i-1])  [하락은 <]
   S_up(i) = i 에서 끝나는 cond 연속 True 개수.
 - 되돌림: 인덱스 기준 K봉 이동창(최소 관측 K).
   DD_K(i) = (c[i]/max(h[i-K+1..i]) - 1)*100 ,  DU_K(i) = (c[i]/min(l[i-K+1..i]) - 1)*100
 - 가속: A(Ls,Ll)(i) = R_Ls(i) - R_Ll(i)
 - 부호일치: NPOS(i) = #{L in (12,48,144,288,864) : R_L(i) > 0} (하나라도 NaN 이면 NaN)

평가
 - 전 종목을 하나로 concat 한 뒤 lib.evaluate 를 한 번 호출한다.
 - 방향 long = rets[k], short = lib.short_of(rets[k]).
 - 신호 밀도 = sig.sum() / mask.sum()  (탐색구간 유효봉 기준). 10% 이상이면 폐기.
 - 표본 500 미만 폐기 (lib.evaluate 의 min_n=500 이 동일 처리).
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import lib

BAR = lib.BAR_MS
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result_momentum.md')

# ----------------------------------------------------------------- GRID (사전 확정)
LB = {3: '15m', 6: '30m', 12: '1h', 24: '2h', 48: '4h', 84: '7h',
      144: '12h', 288: '24h', 864: '3d', 2016: '7d'}
LKEYS = sorted(LB)

ABS_HI = [2.0, 5.0, 10.0, 20.0]          # R_L > x
ABS_LO = [-2.0, -5.0, -10.0, -20.0]      # R_L < x
Z_HI = [1.28, 1.64, 2.33]                # 상위 약 10% / 5% / 1%
Z_LO = [-1.28, -1.64, -2.33]

PAIRS = [(3, 24), (6, 48), (12, 144), (24, 288), (48, 288),
         (12, 288), (144, 864), (288, 2016)]
ACC_THR = [5.0, 10.0, -5.0, -10.0]

STREAK_THR = [5, 7, 10, 15]

KWIN = [48, 288, 2016]
DD_THR = [-10.0, -20.0, -30.0, -50.0]
DU_THR = [10.0, 20.0, 30.0, 50.0]

NPOS_L = [12, 48, 144, 288, 864]

ZWIN, ZMINP = 2016, 500
TOL = 1.5

HOR = ['1h', '4h', '12h', '24h', '48h']
DENS_MAX = 0.10
MIN_N = 500


# ----------------------------------------------------------------- 특징 계산
def lookback_idx(t, L):
    """t[j] <= t[i]-L*BAR 인 마지막 j. 유효하지 않으면 -1."""
    tgt = t - L * BAR
    j = np.searchsorted(t, tgt, side='right') - 1
    bad = (j < 0)
    jj = np.where(bad, 0, j)
    span = t - t[jj]
    bad |= (span > TOL * L * BAR)
    return np.where(bad, -1, j)


def roll(x, win, minp):
    return pd.Series(x)


def feats_for(sym):
    d = lib.load(sym)
    t, o, h, l, c = d['t'], d['o'], d['h'], d['l'], d['c']
    n = len(t)
    mask, rets = lib.fwd_returns(d, 'disc')       # <-- 'disc' 전용

    R = {}
    for L in LKEYS:
        j = lookback_idx(t, L)
        ok = j >= 0
        jj = np.where(ok, j, 0)
        r = (c / c[jj] - 1.0) * 100.0
        r[~ok] = np.nan
        R[L] = r.astype(np.float32)

    Z = {}
    for L in LKEYS:
        s = pd.Series(R[L].astype(np.float64))
        rm = s.rolling(ZWIN, min_periods=ZMINP).mean()
        rs = s.rolling(ZWIN, min_periods=ZMINP).std()
        z = ((s - rm) / rs.where(rs > 0)).to_numpy()
        Z[L] = z.astype(np.float32)

    cont = np.zeros(n, bool)
    cont[1:] = (t[1:] - t[:-1]) == BAR
    up = np.zeros(n, bool); dn = np.zeros(n, bool)
    up[1:] = cont[1:] & (c[1:] > c[:-1])
    dn[1:] = cont[1:] & (c[1:] < c[:-1])
    idx = np.arange(n)

    def streak(cond):
        rst = np.where(~cond, idx, 0)
        return (idx - np.maximum.accumulate(rst)).astype(np.int16)

    S_up, S_dn = streak(up), streak(dn)

    DD, DU = {}, {}
    hs, ls = pd.Series(h.astype(np.float64)), pd.Series(l.astype(np.float64))
    for K in KWIN:
        mx = hs.rolling(K, min_periods=K).max().to_numpy()
        mn = ls.rolling(K, min_periods=K).min().to_numpy()
        DD[K] = ((c / mx - 1.0) * 100.0).astype(np.float32)
        DU[K] = ((c / mn - 1.0) * 100.0).astype(np.float32)

    fin = np.ones(n, bool)
    npos = np.zeros(n, np.float32)
    for L in NPOS_L:
        fin &= np.isfinite(R[L])
        npos += (R[L] > 0).astype(np.float32)
    npos[~fin] = np.nan

    out = {'mask': mask, 't': t}
    for k in HOR:
        out['r_' + k] = rets[k].astype(np.float32)
    for L in LKEYS:
        out['R%d' % L] = R[L]
        out['Z%d' % L] = Z[L]
    for K in KWIN:
        out['DD%d' % K] = DD[K]
        out['DU%d' % K] = DU[K]
    out['SU'] = S_up
    out['SD'] = S_dn
    out['NPOS'] = npos
    return out


def build():
    syms = lib.symbols()
    lens = []
    parts = []
    t0 = time.time()
    for i, s in enumerate(syms):
        parts.append(feats_for(s))
        lens.append(len(parts[-1]['t']))
        if (i + 1) % 40 == 0:
            print('  build %d/%d  %.0fs' % (i + 1, len(syms), time.time() - t0), flush=True)
    keys = list(parts[0].keys())
    G = {}
    for k in keys:
        G[k] = np.concatenate([p[k] for p in parts])
        for p in parts:
            p[k] = None
    print('  total bars', len(G['t']), 'mask', int(G['mask'].sum()), flush=True)
    return G


# ----------------------------------------------------------------- 신호 격자
def signals(G):
    """(이름, bool 배열) 생성기. 이름은 재현 가능한 정의 문자열."""
    for L in LKEYS:
        for x in ABS_HI:
            yield ('R_%s > %+g%%' % (LB[L], x), G['R%d' % L] > x)
        for x in ABS_LO:
            yield ('R_%s < %+g%%' % (LB[L], x), G['R%d' % L] < x)
        for x in Z_HI:
            yield ('Z_%s > %+g' % (LB[L], x), G['Z%d' % L] > x)
        for x in Z_LO:
            yield ('Z_%s < %+g' % (LB[L], x), G['Z%d' % L] < x)
    for (a, b) in PAIRS:
        A = G['R%d' % a] - G['R%d' % b]
        for x in ACC_THR:
            op = '>' if x > 0 else '<'
            yield ('ACC(R_%s - R_%s) %s %+g%%p' % (LB[a], LB[b], op, x),
                   (A > x) if x > 0 else (A < x))
        yield ('R_%s>0 & R_%s<0' % (LB[a], LB[b]), (G['R%d' % a] > 0) & (G['R%d' % b] < 0))
        yield ('R_%s<0 & R_%s>0' % (LB[a], LB[b]), (G['R%d' % a] < 0) & (G['R%d' % b] > 0))
    for x in STREAK_THR:
        yield ('연속상승봉 >= %d' % x, G['SU'] >= x)
        yield ('연속하락봉 >= %d' % x, G['SD'] >= x)
    for K in KWIN:
        for x in DD_THR:
            yield ('DD_%d봉(고점대비) < %+g%%' % (K, x), G['DD%d' % K] < x)
        for x in DU_THR:
            yield ('DU_%d봉(저점대비) > %+g%%' % (K, x), G['DU%d' % K] > x)
    yield ('NPOS==5 (1h,4h,12h,24h,3d 전부 상승)', G['NPOS'] == 5)
    yield ('NPOS==0 (1h,4h,12h,24h,3d 전부 하락)', G['NPOS'] == 0)


def main():
    G = build()
    mask = G['mask']
    nmask = int(mask.sum())
    ts = G['t']
    R = {k: G['r_' + k] for k in HOR}
    S = {k: lib.short_of(G['r_' + k]) for k in HOR}

    rows = []
    dropped_dense = []
    nfeat = 0
    ncomb = 0
    t0 = time.time()
    for name, cond in signals(G):
        nfeat += 1
        sig = mask & np.asarray(cond, bool)
        dens = sig.sum() / nmask
        if dens >= DENS_MAX:
            dropped_dense.append((name, dens))
            continue
        for k in HOR:
            for dirn, arr in (('롱', R[k]), ('숏', S[k])):
                ncomb += 1
                e = lib.evaluate(sig, arr, ts, min_n=MIN_N)
                if not e.get('ok'):
                    continue
                rows.append(dict(feat=name, dirn=dirn, hor=k, dens=dens, **e))
        if nfeat % 25 == 0:
            print('  eval feat %d  %.0fs' % (nfeat, time.time() - t0), flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(os.path.dirname(OUT_MD), 'sweep_momentum_all.csv'),
              index=False, encoding='utf-8')

    ntested = nfeat * len(HOR) * 2
    sel = df[(df['mean'] > 0) & (df['n'] >= MIN_N) & (df['sign_stable'])].copy()
    sel = sel.sort_values('mean', ascending=False).head(15)

    L = []
    L.append('# 업비트 5분봉 — 모멘텀/수익률 계열 특징 격자 탐색 결과\n')
    L.append('- 구간: `lib.fwd_returns(d, \'disc\')` 탐색 구간만 (`hold` 미호출)')
    L.append('- 종목 239개 전량, 전 종목 concat 후 `lib.evaluate` 1회 호출')
    L.append('- 탐색구간 유효봉(mask) 총 **%s개**' % f'{nmask:,}')
    L.append('- 특징(조건) 개수 **%d개**, 검정한 조합 = 특징 × 지평 5 × 방향 2 = **%d개**'
             % (nfeat, ntested))
    L.append('- 그중 밀도 10%% 이상으로 폐기한 특징 **%d개**, 실제 평가된 조합 **%d개**, '
             '표본 500건 이상으로 결과가 나온 조합 **%d개**'
             % (len(dropped_dense), ncomb, len(df)))
    L.append('- 채택 기준: 평균 > 0 **및** n >= 500 **및** sign_stable = True. '
             '해당 조합 **%d개**, 아래는 평균 내림차순 상위 15개.\n'
             % int(((df['mean'] > 0) & (df['sign_stable'])).sum()))
    L.append('| 특징 정의(재현 가능) | 방향 | 지평 | n | 평균% | 중앙% | 승률% | '
             '최대기여일제외 평균% | 부호유지 |')
    L.append('|---|---|---|---:|---:|---:|---:|---:|---|')
    if len(sel) == 0:
        L.append('\n**조건 충족 0개**\n')
    else:
        for _, r in sel.iterrows():
            L.append('| %s | %s | %s | %d | %.3f | %.3f | %.1f | %.3f | %s |' % (
                r['feat'], r['dirn'], r['hor'], r['n'], r['mean'], r['median'],
                r['win'], r['mean_ex_topday'], r['sign_stable']))
    # ---- 기준선(무조건) --------------------------------------------------
    L.append('\n## 기준선 — 조건 없이 전체 봉(mask)에 진입했을 때')
    L.append('| 방향 | 지평 | n | 평균% | 중앙% | 승률% | 최대기여일제외 평균% |')
    L.append('|---|---|---:|---:|---:|---:|---:|')
    base = {}
    for k in HOR:
        for dirn, arr in (('롱', R[k]), ('숏', S[k])):
            e = lib.evaluate(mask, arr, ts, min_n=MIN_N)
            base[(dirn, k)] = e['mean']
            L.append('| %s | %s | %d | %.3f | %.3f | %.1f | %.3f |' %
                     (dirn, k, e['n'], e['mean'], e['median'], e['win'], e['mean_ex_topday']))
    L.append('\n표의 평균은 이 기준선과 비교해야 의미가 있다. '
             '아래는 상위 15개의 "기준선 대비 초과평균(%p)".')
    L.append('| 특징 | 방향 | 지평 | 평균% | 기준선% | 초과%p |')
    L.append('|---|---|---|---:|---:|---:|')
    for _, r in sel.iterrows():
        b = base[(r['dirn'], r['hor'])]
        L.append('| %s | %s | %s | %.3f | %.3f | %+.3f |' %
                 (r['feat'], r['dirn'], r['hor'], r['mean'], b, r['mean'] - b))

    # ---- 자체 검산 -------------------------------------------------------
    L.append('\n## 자체 검산')
    L.append('- 전 종목 concat 총 봉수 = %s (npz 원본 합계와 일치해야 함)' % f'{len(ts):,}')
    ck = []
    for k in HOR:
        ck.append('%s: %s' % (k, f"{int((mask & np.isfinite(R[k])).sum()):,}"))
    L.append('- 지평별 유효 표본(NaN 제외, 무조건) = ' + ' / '.join(ck))
    L.append('- 롱/숏 표본수는 동일해야 한다: ' +
             ', '.join('%s %s' % (k, int((mask & np.isfinite(R[k])).sum()) ==
                                  int((mask & np.isfinite(S[k])).sum())) for k in HOR))
    if len(sel):
        r0 = sel.iloc[0]
        nm, cond0 = next((a, b) for a, b in signals(G) if a == r0['feat'])
        s0 = mask & np.asarray(cond0, bool)
        arr0 = R[r0['hor']] if r0['dirn'] == '롱' else S[r0['hor']]
        L.append('- 1위 행 재계산: n(직접 카운트)=%d, evaluate n=%d, 밀도=%.4f'
                 % (int((s0 & np.isfinite(arr0)).sum()), int(r0['n']), r0['dens']))
    L.append('\n## 다중검정 주의')
    L.append('%d개 조합을 검정했으므로 우연히 평균>0·부호유지를 통과하는 건이 다수 나온다. '
             '위 표는 "발견"이 아니라 "후보"다. 확인 구간(hold)은 봉인 상태로 미사용.' % ntested)

    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('\n'.join(L))
    print('\n[done] %.0fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
