"""바이낸스 1년 전수 탐색 공용 계산틀. 직접 계산 금지 — 이 함수만 쓴다.
사전등록: docs/PREREG_SWEEP_BINANCE.md
"""
import os, glob, hashlib
import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
PQ = os.path.join(D, 'pq'); FD = os.path.join(D, 'fund')
BAR = 300000
COST_SIDE = 0.0006
HORIZONS = {'1h': 12, '4h': 48, '12h': 144, '24h': 288, '48h': 576}
WIN_S, WIN_E = 1754006400000, 1785523200000     # 2025-08-01 ~ 2026-08-01

def is_holdout(sym):
    return int(hashlib.md5(sym.encode()).hexdigest(), 16) % 4 == 0

def symbols(half):
    """half: 'disc'(탐색, 75%) | 'hold'(봉인, 25%)"""
    assert half in ('disc', 'hold')
    ss = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ, '*.npz')))
    return [s for s in ss if is_holdout(s) == (half == 'hold')]

def load(sym):
    z = np.load(os.path.join(PQ, sym + '.npz'))
    return {k: z[k] for k in z.files}

def _cumfund(sym, t):
    p = os.path.join(FD, sym + '.npz')
    if not os.path.exists(p):
        return np.zeros(len(t))
    z = np.load(p); ft = z[z.files[0]]; fr = z[z.files[1]]
    cs = np.concatenate(([0.0], np.cumsum(fr)))
    return cs[np.searchsorted(ft, t, 'right')]

def fwd_returns(d, sym):
    """반환 (mask, long, short).
    long[k]/short[k] = 명목가 기준 순수익률 %(왕복 비용 + 펀딩 실측 반영). NaN 있음.
    진입 = 다음 봉 시가, 청산 = h봉 뒤 종가. 연속성 위반은 NaN."""
    t, o, c = d['t'], d['o'], d['c']
    n = len(t)
    cf = _cumfund(sym, t)
    ent = np.full(n, np.nan); ent[:-1] = o[1:]
    cont = np.zeros(n, bool); cont[:-1] = (t[1:] - t[:-1]) == BAR
    L, S = {}, {}
    fee = COST_SIDE * 2 * 100.0
    for k, h in HORIZONS.items():
        ex = np.full(n, np.nan); ok = np.zeros(n, bool); fnd = np.full(n, np.nan)
        if n > h + 1:
            ex[:n-h-1] = c[h+1:]
            ok[:n-h-1] = (t[h+1:] - t[1:n-h]) == h * BAR
            fnd[:n-h-1] = (cf[h+1:] - cf[1:n-h]) * 100.0   # 보유구간 누적 펀딩률 %
        g = (ex / ent - 1.0) * 100.0
        bad = ~(cont & ok)
        l = g - fnd - fee          # 롱은 펀딩 지불
        s = -g + fnd - fee         # 숏은 펀딩 수취
        l[bad] = np.nan; s[bad] = np.nan
        L[k] = l; S[k] = s
    inwin = (t >= WIN_S) & (t < WIN_E)
    return inwin & cont, L, S

def day_of(t):   return (t // 86400000).astype(np.int64)
def month_of(t): return np.array([int(x) for x in ((t // 86400000) // 30)])

def evaluate(sig, ret, t, min_n=500, min_syms=None, sym_ids=None):
    """전 종목 concat 배열에 한 번 호출한다.
    반환: n, mean, median, win, ndays, mean_ex_topday, sign_stable,
          months_total, months_same_sign, ok"""
    import datetime as dt
    m = np.asarray(sig, bool) & np.isfinite(ret)
    n = int(m.sum())
    if n < min_n:
        return {'n': n, 'ok': False}
    r = ret[m]; tt = t[m]
    d = day_of(tt); ud = np.unique(d)
    contrib = {x: r[d == x].sum() for x in ud}
    top = max(contrib, key=lambda k: abs(contrib[k]))
    ex = r[d != top]
    mo = np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in tt])
    umo = np.unique(mo)
    same = sum(1 for x in umo if np.sign(r[mo == x].mean()) == np.sign(r.mean()))
    out = {'n': n, 'mean': float(r.mean()), 'median': float(np.median(r)),
           'win': float((r > 0).mean() * 100), 'ndays': int(len(ud)),
           'mean_ex_topday': float(ex.mean()) if len(ex) else np.nan,
           'sign_stable': bool(len(ex) and np.sign(r.mean()) == np.sign(ex.mean())),
           'months_total': int(len(umo)), 'months_same_sign': int(same), 'ok': True}
    if sym_ids is not None:
        out['nsyms'] = int(len(np.unique(np.asarray(sym_ids)[m])))
    return out
