"""모멘텀/수익률 계열 특징 전수 스윕 (바이낸스 USDT 무기한선물 5분봉 1년, disc 610종목).

사전등록 설계 (코드에 격자 확정 -> 전수 실행 -> 결과 그대로 보고):
  * 진입 후보 봉  : UTC 정시 격자 (t//BAR % 12 == 0). 5분봉 전수는 중복표본이며
                    evaluate 비용이 과대해 1시간 격자로 고정. 지평 1h~48h 대비 충분.
  * 수익률/비용/펀딩/연속성 : 전부 swlib.fwd_returns 만 사용.
  * 분위 임계  : 전 종목 풀링(pooled) 분위수.
  * 필터       : 밀도<10%, n>=500, 종목>=30, 날짜>=30.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import swlib as L

D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get('M5BT_CACHE', os.path.join(D, '_mom_cache.npz'))
BAR = L.BAR
STRIDE = 12                     # 1시간 격자
HZ = ['1h', '4h', '12h', '24h', '48h']

PERIODS = {'15m': 3, '30m': 6, '1h': 12, '2h': 24, '4h': 48, '7h': 84,
           '12h': 144, '24h': 288, '3d': 864, '7d': 2016}
ACC_PAIRS = [('30m', '4h'), ('1h', '4h'), ('1h', '12h'), ('2h', '12h'),
             ('4h', '24h'), ('4h', '7d'), ('12h', '3d'), ('24h', '7d')]
EXT_W = [48, 288, 2016]
Z_KEYS = ['1h', '4h', '24h']
Z_WIN = 2016

FEATS = ([f'r_{k}' for k in PERIODS] +
         [f'acc_{a}_{b}' for a, b in ACC_PAIRS] +
         [f'dd{w}' for w in EXT_W] + [f'du{w}' for w in EXT_W] +
         ['cu', 'cd'] + [f'z_{k}' for k in Z_KEYS])
FI = {f: i for i, f in enumerate(FEATS)}


# ---------------------------------------------------------------- 특징 계산
def _roll(x, w, kind):
    """연속성 위반 구간은 NaN. kind: 'max'|'min'|'mean'|'std'"""
    import pandas as pd
    s = pd.Series(x)
    r = s.rolling(w, min_periods=w)
    return {'max': r.max(), 'min': r.min(), 'mean': r.mean(),
            'std': r.std(ddof=0)}[kind].to_numpy()


def features(d):
    t, c = d['t'], d['c']
    n = len(t)
    F = np.full((n, len(FEATS)), np.nan, np.float64)
    R = {}
    for k, p in PERIODS.items():
        r = np.full(n, np.nan)
        if n > p:
            r[p:] = (c[p:] / c[:-p] - 1.0) * 100.0
            bad = (t[p:] - t[:-p]) != p * BAR
            r[p:][bad] = np.nan
        R[k] = r
        F[:, FI[f'r_{k}']] = r
    for a, b in ACC_PAIRS:
        F[:, FI[f'acc_{a}_{b}']] = R[a] - R[b]
    for w in EXT_W:
        cont = np.zeros(n, bool)
        if n >= w:
            cont[w - 1:] = (t[w - 1:] - t[:n - w + 1]) == (w - 1) * BAR
        mx = _roll(c, w, 'max'); mn = _roll(c, w, 'min')
        dd = (c / mx - 1.0) * 100.0
        du = (c / mn - 1.0) * 100.0
        dd[~cont] = np.nan; du[~cont] = np.nan
        F[:, FI[f'dd{w}']] = dd
        F[:, FI[f'du{w}']] = du
    ct = np.zeros(n, bool); ct[1:] = (t[1:] - t[:-1]) == BAR
    up = np.zeros(n, bool); dn = np.zeros(n, bool)
    up[1:] = ct[1:] & (c[1:] > c[:-1])
    dn[1:] = ct[1:] & (c[1:] < c[:-1])
    idx = np.arange(n)
    F[:, FI['cu']] = idx - np.maximum.accumulate(np.where(~up, idx, -1))
    F[:, FI['cd']] = idx - np.maximum.accumulate(np.where(~dn, idx, -1))
    for k in Z_KEYS:
        r = R[k]
        mu = _roll(r, Z_WIN, 'mean'); sd = _roll(r, Z_WIN, 'std')
        with np.errstate(invalid='ignore', divide='ignore'):
            F[:, FI[f'z_{k}']] = (r - mu) / sd
    return F


# ---------------------------------------------------------------- 데이터 적재
def build_cache():
    syms = L.symbols('disc')
    FA, TA, SA = [], [], []
    LA = {k: [] for k in HZ}; SHA = {k: [] for k in HZ}
    t0 = time.time()
    for i, sym in enumerate(syms):
        d = L.load(sym)
        mask, LO, SH = L.fwd_returns(d, sym)
        sel = mask & (((d['t'] // BAR) % STRIDE) == 0)
        if not sel.any():
            continue
        F = features(d)
        FA.append(F[sel].astype(np.float32))
        TA.append(d['t'][sel])
        SA.append(np.full(int(sel.sum()), i, np.int16))
        for k in HZ:
            LA[k].append(LO[k][sel].astype(np.float32))
            SHA[k].append(SH[k][sel].astype(np.float32))
        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{len(syms)} {time.time()-t0:.0f}s', flush=True)
    out = {'F': np.concatenate(FA), 't': np.concatenate(TA),
           'sid': np.concatenate(SA)}
    for k in HZ:
        out['L_' + k] = np.concatenate(LA[k])
        out['S_' + k] = np.concatenate(SHA[k])
    np.savez(CACHE, **out)
    print('cache rows', len(out['t']), f'{time.time()-t0:.0f}s')
    return out


def get_data():
    if os.path.exists(CACHE):
        z = np.load(CACHE)
        return {k: z[k] for k in z.files}
    return build_cache()


# ---------------------------------------------------------------- 규칙 격자
QS = [0.005, 0.01, 0.02, 0.05, 0.08]
COMBOS = [  # (단기키, 단기tail, 장기키, 장기tail)  단기 반전 / 추세 조합
    ('1h', 'hi', '24h', 'lo'), ('1h', 'lo', '24h', 'hi'),
    ('1h', 'hi', '24h', 'hi'), ('1h', 'lo', '24h', 'lo'),
    ('4h', 'hi', '7d', 'lo'), ('4h', 'lo', '7d', 'hi'),
    ('4h', 'hi', '7d', 'hi'), ('4h', 'lo', '7d', 'lo'),
]
SIGN_KEYS = ['1h', '4h', '24h']


def build_rules(F, Q):
    """반환: [(이름, 정의문자열, bool mask)] — 격자는 여기서 전수 확정."""
    def col(name):
        return F[:, FI[name]]
    rules = []

    def add(name, defn, m):
        rules.append((name, defn, m))

    # F1: 단일 기간 수익률 분위 극단
    for k in PERIODS:
        x = col(f'r_{k}')
        for q in QS:
            hi = Q[f'r_{k}'][1.0 - q]; lo = Q[f'r_{k}'][q]
            add(f'F1|r_{k}|hi{q}', f'ret({k}) >= {hi:.3f}% (풀링 상위 {q*100:g}%)', x >= hi)
            add(f'F1|r_{k}|lo{q}', f'ret({k}) <= {lo:.3f}% (풀링 하위 {q*100:g}%)', x <= lo)
    # F2: 가속(단기-장기) 분위 극단
    for a, b in ACC_PAIRS:
        nm = f'acc_{a}_{b}'; x = col(nm)
        for q in (0.01, 0.05):
            hi = Q[nm][1.0 - q]; lo = Q[nm][q]
            add(f'F2|{nm}|hi{q}', f'ret({a})-ret({b}) >= {hi:.3f}%p (상위 {q*100:g}%)', x >= hi)
            add(f'F2|{nm}|lo{q}', f'ret({a})-ret({b}) <= {lo:.3f}%p (하위 {q*100:g}%)', x <= lo)
    # F3: 단기x장기 분위 조합 (각 10% 꼬리)
    for sk, st, lk, lt in COMBOS:
        xs = col(f'r_{sk}'); xl = col(f'r_{lk}')
        ms = xs >= Q[f'r_{sk}'][0.9] if st == 'hi' else xs <= Q[f'r_{sk}'][0.1]
        ml = xl >= Q[f'r_{lk}'][0.9] if lt == 'hi' else xl <= Q[f'r_{lk}'][0.1]
        sy = {'hi': '상위10%', 'lo': '하위10%'}
        add(f'F3|{sk}{st}_{lk}{lt}', f'ret({sk}) {sy[st]} AND ret({lk}) {sy[lt]}', ms & ml)
    # F4: 연속 상승/하락 봉 수
    cu, cd = col('cu'), col('cd')
    for k in (6, 8, 10, 12, 15):
        add(f'F4|cu>={k}', f'연속 상승봉 {k}개 이상', cu >= k)
        add(f'F4|cd>={k}', f'연속 하락봉 {k}개 이상', cd >= k)
    # F5: 최근 고점대비 낙폭 / 저점대비 상승폭
    for w in EXT_W:
        dd = col(f'dd{w}'); du = col(f'du{w}')
        for x in (10, 20, 30, 40, 50):
            add(f'F5|dd{w}<=-{x}', f'{w}봉 고점대비 낙폭 <= -{x}%', dd <= -x)
            add(f'F5|du{w}>={x}', f'{w}봉 저점대비 상승폭 >= +{x}%', du >= x)
    # F6: 부호 조합 (1h,4h,24h)
    sg = {k: np.sign(col(f'r_{k}')) for k in SIGN_KEYS}
    big = np.abs(col('r_24h')) >= Q['abs_r_24h'][0.9]
    for p in range(8):
        want = [1 if (p >> j) & 1 else -1 for j in range(3)]
        m = np.ones(len(F), bool)
        for k, w in zip(SIGN_KEYS, want):
            m &= (sg[k] == w)
        lab = ''.join('+' if w > 0 else '-' for w in want)
        add(f'F6|sign{lab}', f'sign(ret1h,ret4h,ret24h) = ({lab[0]},{lab[1]},{lab[2]})', m)
        add(f'F6|sign{lab}+big', f'부호({lab}) AND |ret24h| 상위10%', m & big)
    # F7: z-score (종목별 2016봉 이동 표준화)
    for k in Z_KEYS:
        z = col(f'z_{k}')
        for a in (2.0, 2.5, 3.0):
            add(f'F7|z_{k}>={a}', f'z(ret {k}, 2016봉) >= +{a}', z >= a)
            add(f'F7|z_{k}<=-{a}', f'z(ret {k}, 2016봉) <= -{a}', z <= -a)
    return rules


# ---------------------------------------------------------------- 실행
def main():
    dat = get_data()
    F, t, sid = dat['F'], dat['t'], dat['sid']
    N = len(t)
    print('rows', N, 'syms', len(np.unique(sid)))

    qlev = sorted(set([q for q in QS] + [1 - q for q in QS] + [0.1, 0.9]))
    Q = {}
    for f in FEATS:
        x = F[:, FI[f]]
        x = x[np.isfinite(x)]
        vals = np.quantile(x, qlev)
        Q[f] = {lv: float(v) for lv, v in zip(qlev, vals)}
    ax = np.abs(F[:, FI['r_24h']]); ax = ax[np.isfinite(ax)]
    Q['abs_r_24h'] = {0.9: float(np.quantile(ax, 0.9))}

    rules = build_rules(F, Q)
    print('rules', len(rules), 'combos =', len(rules) * len(HZ) * 2)

    rows = []
    dropped = {'density': 0, 'n': 0}
    for ri, (name, defn, m) in enumerate(rules):
        m = np.asarray(m, bool)   # NaN 비교는 이미 False
        dens = float(m.sum()) / N
        if dens >= 0.10:
            dropped['density'] += 1
            continue
        if m.sum() < 500:
            dropped['n'] += 1
            continue
        idx = np.flatnonzero(m)
        tt = t[idx]; ss = sid[idx]
        one = np.ones(len(idx), bool)
        for h in HZ:
            for dirn, pre in (('LONG', 'L_'), ('SHORT', 'S_')):
                r = dat[pre + h][idx].astype(np.float64)
                e = L.evaluate(one, r, tt, min_n=500, sym_ids=ss)
                if not e.get('ok'):
                    continue
                e.update(rule=name, defn=defn, hz=h, dir=dirn, dens=dens)
                rows.append(e)
        if (ri + 1) % 25 == 0:
            print(f'  rule {ri+1}/{len(rules)}', flush=True)
    print('dropped', dropped, 'evaluated rows', len(rows))

    # 2025-10 별도 성적 (상위 후보용)
    def oct25(m_name):
        pass

    json.dump(rows, open(os.path.join(D, '_mom_rows.json'), 'w'), default=float)

    # ---- 필터 & 정렬
    keep = [r for r in rows if r['mean'] > 0 and r['n'] >= 500
            and r.get('nsyms', 0) >= 30 and r['ndays'] >= 30 and r['sign_stable']]
    keep.sort(key=lambda r: -r['mean'])
    top = keep[:15]

    # 상위 후보 2025-10 성적
    oct_res = []
    rmap = {n: (d, mm) for n, d, mm in rules}
    for r in top:
        _, mm = rmap[r['rule']]
        m = np.asarray(mm, bool)
        idx = np.flatnonzero(m)
        tt = t[idx]
        import datetime as dt
        mo = np.array([dt.datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m') for x in tt])
        sel = mo == '2025-10'
        if sel.sum() == 0:
            oct_res.append({'rule': r['rule'], 'hz': r['hz'], 'dir': r['dir'], 'n': 0})
            continue
        rr = dat[('L_' if r['dir'] == 'LONG' else 'S_') + r['hz']][idx][sel].astype(np.float64)
        rr = rr[np.isfinite(rr)]
        oct_res.append({'rule': r['rule'], 'hz': r['hz'], 'dir': r['dir'],
                        'n': int(len(rr)),
                        'mean': float(rr.mean()) if len(rr) else float('nan'),
                        'median': float(np.median(rr)) if len(rr) else float('nan'),
                        'win': float((rr > 0).mean() * 100) if len(rr) else float('nan')})

    # 기준선: 무조건 진입
    base = []
    allm = np.ones(N, bool)
    for h in HZ:
        for dirn, pre in (('LONG', 'L_'), ('SHORT', 'S_')):
            e = L.evaluate(allm, dat[pre + h].astype(np.float64), t, min_n=500, sym_ids=sid)
            e.update(hz=h, dir=dirn)
            base.append(e)

    write_report(rules, rows, keep, top, oct_res, base, N, dropped)


def write_report(rules, rows, keep, top, oct_res, base, N, dropped):
    def fm(x):
        return 'nan' if x is None or (isinstance(x, float) and not np.isfinite(x)) else f'{x:.3f}'
    L_ = []
    A = L_.append
    A('# 모멘텀/수익률 계열 전수 스윕 결과 (바이낸스 USDT 무기한선물 5분봉, 2025-08-01~2026-08-01)\n')
    A(f'- 대상: `swlib.symbols(\'disc\')` 610종목 (봉인 25%는 미사용)')
    A(f'- 진입 후보 봉: UTC 정시 격자(5분봉 12개마다 1개), 총 **{N:,}** 후보 봉')
    A(f'- 수익률·비용(왕복 0.12%)·펀딩·연속성: 전부 `swlib.fwd_returns` 계산값')
    A(f'- **검정한 총 조합 수: {len(rules)}개 특징 규칙 x 5지평 x 롱/숏 2방향 = '
      f'{len(rules)*len(HZ)*2:,}조합** (밀도>=10%로 사전 탈락 {dropped["density"]}규칙, '
      f'표본<500 탈락 {dropped["n"]}규칙 -> 실제 평가 {len(rows):,}조합)\n')

    A('## 1. 무조건 진입 기준선 (조건 없이 전 후보 봉)\n')
    A('| 방향 | 지평 | n | 평균% | 중앙% | 승률% |')
    A('|---|---|---|---|---|---|')
    for e in base:
        A(f"| {e['dir']} | {e['hz']} | {e['n']:,} | {fm(e['mean'])} | {fm(e['median'])} | {fm(e['win'])} |")
    A('')

    A('## 2. 조건 충족 상위 15개\n')
    A('필터: 평균>0 · n>=500 · 종목>=30 · 날짜>=30 · 부호유지=True · 밀도<10%\n')
    if not top:
        A('**조건 충족 0개**\n')
    else:
        A('| 특징 정의 | 방향 | 지평 | n | 종목수 | 날짜수 | 평균% | 중앙% | 승률% | 최대기여일제외 | 월 부호일치/총월 | 밀도% |')
        A('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for e in top:
            star = ' **[8/12+]**' if e['months_same_sign'] >= 8 else ''
            A(f"| {e['defn']} | {e['dir']} | {e['hz']} | {e['n']:,} | {e.get('nsyms')} | "
              f"{e['ndays']} | {fm(e['mean'])} | {fm(e['median'])} | {fm(e['win'])} | "
              f"{fm(e['mean_ex_topday'])} | **{e['months_same_sign']}/{e['months_total']}**{star} | "
              f"{e['dens']*100:.2f} |")
        A('')
        n8 = sum(1 for e in top if e['months_same_sign'] >= 8)
        A(f'월 부호일치 8/12 이상: **{n8}개** (위 표에서 `[8/12+]` 표시)\n')

    A('## 3. 상위 후보의 2025-10 (알트 대폭등) 한 달 성적\n')
    A('| 특징 정의 | 방향 | 지평 | 10월 n | 10월 평균% | 10월 중앙% | 10월 승률% |')
    A('|---|---|---|---|---|---|---|')
    dmap = {(e['rule'], e['hz'], e['dir']): e['defn'] for e in rows}
    for o in oct_res:
        A(f"| {dmap.get((o['rule'],o['hz'],o['dir']), o['rule'])} | {o['dir']} | {o['hz']} | "
          f"{o['n']:,} | {fm(o.get('mean'))} | {fm(o.get('median'))} | {fm(o.get('win'))} |")
    A('')
    A(f'전체 조건 충족 조합 수: {len(keep)}개 (상위 15개만 위에 표기)\n')
    open(os.path.join(D, 'bresult_momentum.md'), 'w', encoding='utf-8').write('\n'.join(L_))
    print('\n'.join(L_))


if __name__ == '__main__':
    main()
