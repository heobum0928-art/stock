"""공용 계산 틀 — 모든 탐색은 이걸 통해서만 한다. 직접 계산 금지.
사전등록: docs/PREREG_FEATURE_SWEEP.md
"""
import glob, os
import numpy as np

SPLIT_MS = 1780716840000        # 2026-06-06 UTC — 변경 금지
PQ = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pq')
COST_SIDE = 0.0006              # 편도 0.06% (수수료+슬리피지)
HORIZONS = {'1h':12, '4h':48, '12h':144, '24h':288, '48h':576}
BAR_MS = 300000

def symbols():
    return sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))

def load(sym):
    z = np.load(os.path.join(PQ, sym+'.npz'))
    return {k: z[k] for k in ('t','o','h','l','c','qv','v')}

def fwd_returns(d, half):
    """진입 = 신호 봉의 '다음 봉 시가'. look-ahead 방지.
    half: 'disc'(탐색) | 'hold'(봉인)
    반환: (mask, {지평: 순수익률(%) 배열}) — 비용 왕복 차감, 롱 기준.
    숏은 부호를 뒤집되 비용은 다시 차감해야 하므로 short_of()를 쓴다."""
    t, o, c = d['t'], d['o'], d['c']
    n = len(t)
    entry = np.full(n, np.nan)
    entry[:-1] = o[1:]                                  # i 봉 신호 -> i+1 봉 시가 진입
    cont = np.zeros(n, bool); cont[:-1] = (t[1:]-t[:-1]) == BAR_MS
    out = {}
    for k, h in HORIZONS.items():
        ex = np.full(n, np.nan)
        if n > h+1:
            ex[:n-h-1] = c[h+1:]
            # 연속성: 진입~청산 구간에 결측이 없어야 함
            okc = np.zeros(n, bool)
            okc[:n-h-1] = (t[h+1:] - t[1:n-h]) == h*BAR_MS
        else:
            okc = np.zeros(n, bool)
        r = (ex/entry - 1.0)*100.0
        r = r - COST_SIDE*2*100.0                        # 왕복 비용
        r[~(cont & okc)] = np.nan
        out[k] = r
    inwin = (t < SPLIT_MS) if half=='disc' else (t >= SPLIT_MS)
    if half not in ('disc','hold'):
        raise ValueError('half must be disc|hold')
    return inwin & cont, out

def short_of(r_long):
    """롱 순수익률에서 숏 순수익률로. 비용은 양쪽 동일하게 이미 차감돼 있으므로
    가격 부분만 뒤집고 비용을 두 번 빼지 않도록 보정한다."""
    gross = r_long + COST_SIDE*2*100.0
    return -gross - COST_SIDE*2*100.0

def day_of(ts_ms):
    return (ts_ms // 86400000).astype(np.int64)

def evaluate(mask, ret, ts, min_n=500):
    """신호 mask에 대한 성적. 단일 날짜 의존도 포함.
    반환 dict: n, mean, median, win, mean_ex_worstday, worstday_share"""
    m = mask & np.isfinite(ret)
    n = int(m.sum())
    if n < min_n:
        return {'n': n, 'mean': np.nan, 'ok': False}
    r = ret[m]; d = day_of(ts[m])
    ud = np.unique(d)
    # 기여도 최대 날짜(절대 기여 기준)
    contrib = {x: r[d==x].sum() for x in ud}
    top = max(contrib, key=lambda k: abs(contrib[k]))
    keep = d != top
    return {'n': n, 'mean': float(r.mean()), 'median': float(np.median(r)),
            'win': float((r>0).mean()*100), 'ndays': int(len(ud)),
            'mean_ex_topday': float(r[keep].mean()) if keep.sum()>0 else np.nan,
            'topday_share': float(contrib[top]/r.sum()) if r.sum()!=0 else np.nan,
            'sign_stable': bool(np.sign(r.mean())==np.sign(r[keep].mean())) if keep.sum()>0 else False,
            'ok': True}
