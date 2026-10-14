"""prereg #59 PREREG_SHORT_BTC7H.md — 급등 숏 신호를 직전 7시간 BTC 수익률로 분할. 주문 없음."""
import pickle, sys
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = 'research/m5bt'
d = pickle.load(open(f'{D}/wide_rows.pkl', 'rb')); a = d['a']
net = np.asarray(a['net'], dtype=float) / 100.0
sym = np.asarray(a['sym']).astype(str)
t0 = np.asarray(a['t0'], dtype=np.int64)
BAR = 300000; N = 84


def ret7(t, c, tq):
    """tq 시각 신호 봉 j 직전(c[j-1]) 대비 7시간 전(c[j-85]) 수익률. 봉 간격이 어긋나면 nan."""
    j = np.searchsorted(t, tq)
    r = np.full(len(tq), np.nan)
    ok = (j < len(t)) & (j >= N + 1)
    jj = j[ok]
    good = (t[jj] == tq[ok]) & ((t[jj - 1] - t[jj - N - 1]) == N * BAR)
    idx = np.nonzero(ok)[0][good]
    jg = jj[good]
    r[idx] = c[jg - 1] / c[jg - N - 1] - 1
    return r


z = np.load(f'{D}/pq/BTCUSDT.npz')
bt = z['t'].astype(np.int64); bc = z['c'].astype(float)
rb = ret7(bt, bc, t0)
ok = ~np.isnan(rb)
print(f'BTC 이력 확보 {ok.sum()}/{len(a)}')

x = net[ok]; r = rb[ok]; day = t0[ok] // 86400000
med = np.median(r)
lo = r <= med; hi = r > med
print(f'BTC 7h 수익률 중앙값 {med*100:+.3f}%  아래 n={lo.sum()} 위 n={hi.sum()}')


def st(m):
    v = x[m]
    return (f'n={m.sum()} 평균 {v.mean()*100:+.2f}% 중앙 {np.median(v)*100:+.2f}% 승률 {(v>0).mean()*100:.0f}% '
            f'최악 {v.min()*100:+.0f}% -50%이하 {(v < -0.5).mean()*100:.1f}%')


def cluster_diff(x_, day_, g1, g2, seed, reps=4000):
    days = np.unique(day_); idx = {dd: np.nonzero(day_ == dd)[0] for dd in days}
    rng = np.random.default_rng(seed); ds = []
    for _ in range(reps):
        sel = np.concatenate([idx[days[p]] for p in rng.integers(0, len(days), len(days))])
        xs = x_[sel]; a1 = g1[sel]; a2 = g2[sel]
        if a1.any() and a2.any():
            ds.append(xs[a1].mean() - xs[a2].mean())
    return np.percentile(ds, [0.5, 99.5]), np.percentile(ds, [2.5, 97.5])


print('BTC 덜 오름(코인 홀로 급등):', st(lo))
print('BTC도 오름(시장 동반)     :', st(hi))
(lo99, hi99), (lo95, hi95) = cluster_diff(x, day, lo, hi, 20261014)
df = x[lo].mean() - x[hi].mean()
print(f'차이(아래 − 위) {df*100:+.2f}%p  99% CI [{lo99*100:+.2f},{hi99*100:+.2f}]  (참고 95% CI [{lo95*100:+.2f},{hi95*100:+.2f}])')

dmed = np.median(day); half = []
for nm, m in (('전반', day <= dmed), ('후반', day > dmed)):
    a1 = x[m & lo]; a2 = x[m & hi]
    dd_ = a1.mean() - a2.mean(); half.append(dd_)
    print(f'  {nm}: 아래 {a1.mean()*100:+.2f}%(n={len(a1)}) 위 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {dd_*100:+.2f}%p')

q1, q2 = np.percentile(r, [100 / 3, 200 / 3])
print('BTC 7h 수익률 3분위:')
for nm, m in (('하', r <= q1), ('중', (r > q1) & (r <= q2)), ('상', r > q2)):
    print(f'  {nm}(≤{q1*100:+.2f}% / {q2*100:+.2f}%): {st(m)}')

# 보조(판정 아님): 코인 자신의 7h 수익률 − BTC 7h 수익률 중앙값 분할
cr = np.full(len(a), np.nan); cache = {}
for s in np.unique(sym):
    try:
        zz = np.load(f'{D}/pq/{s}.npz'); m = sym == s
        cr[m] = ret7(zz['t'].astype(np.int64), zz['c'].astype(float), t0[m])
    except Exception:
        pass
ex = cr - rb
okx = ok & ~np.isnan(ex)
print(f'\n[보조] 코인 7h 수익률 확보 {okx.sum()}/{len(a)}, 코인 7h 수익률 중앙값 {np.nanmedian(cr)*100:+.1f}%')
xe = net[okx]; ee = ex[okx]; de = t0[okx] // 86400000
me = np.median(ee); l2 = ee <= me; h2 = ee > me
(l99, h99), _ = cluster_diff(xe, de, l2, h2, 20261014)
print(f'  초과급등 작은쪽 n={l2.sum()} 평균 {xe[l2].mean()*100:+.2f}% / 큰쪽 n={h2.sum()} 평균 {xe[h2].mean()*100:+.2f}% '
      f'차이(작−큰) {(xe[l2].mean()-xe[h2].mean())*100:+.2f}%p 99%CI [{l99*100:+.2f},{h99*100:+.2f}]')

if lo.sum() < 300 or hi.sum() < 300:
    verdict = '판별 불가'
else:
    same = all(np.sign(h) == np.sign(df) for h in half)
    verdict = '성립' if ((lo99 > 0 or hi99 < 0) and same) else '기각'
direction = '아래(코인 홀로 급등)가 더 좋음(숏 +)' if df > 0 else '위(시장 동반)가 더 좋음(숏 +)'
print('판정:', verdict, '| 방향:', direction)
