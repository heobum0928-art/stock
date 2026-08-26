"""PREREG_DD_SPEED.md 4절 판정 — 5개 기준."""
import numpy as np, datetime as dt
a = np.load('ddspeed.npy')
rng = np.random.default_rng(20260826)
disc = ~a['hold']; hold = a['hold']
mo = np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in a['t0']])

FEATS = [('gap', '1. 가속구간 소요(분)', '작을수록 급함'),
         ('add1h', '2. 직후 1시간 추가역행(%p)', '클수록 급함'),
         ('accel', '3. 가속도(비율)', '클수록 급함')]

def boot(v, m, q1, q3, n=4000):
    us = np.unique(a['sym']); idx = {s: np.flatnonzero(a['sym'] == s) for s in us}
    out = []
    for _ in range(n):
        ii = np.concatenate([idx[us[p]] for p in rng.integers(0, len(us), len(us))])
        vv = a[m][ii] if False else None
        break
    return None

res = []
print('=' * 104)
print('PREREG_DD_SPEED.md 판정 — 역행 속도로 생존을 가를 수 있는가')
print('=' * 104)
print('대상 {}건 (탐색 {} / 봉인 {}), 검열(-40% 미도달) {}건'.format(
    len(a), disc.sum(), hold.sum(), int(a['cens'].sum())))
print()
print('{:28s} {:>8} {:>10} {:>10} {:>19} {:>10}'.format('특징', 'n(탐색)', '상위3분위', '하위3분위', '차이 부트95%CI', '봉인차이'))
print('-' * 104)

us = np.unique(a['sym']); IDX = {s: np.flatnonzero(a['sym'] == s) for s in us}
for key, label, note in FEATS:
    v = a[key]
    m = np.isfinite(v) & disc
    if m.sum() < 100:
        print('{:28s} 표본부족'.format(label)); res.append(None); continue
    q1, q3 = np.percentile(v[m], [33.33, 66.67])
    lo_m = m & (v <= q1); hi_m = m & (v >= q3)
    d = a['ret'][hi_m].mean() - a['ret'][lo_m].mean()
    bs = []
    for _ in range(4000):
        ii = np.concatenate([IDX[us[p]] for p in rng.integers(0, len(us), len(us))])
        vv = v[ii]; rr = a['ret'][ii]; dd = disc[ii] & np.isfinite(vv)
        L = dd & (vv <= q1); H = dd & (vv >= q3)
        if L.sum() < 20 or H.sum() < 20: continue
        bs.append(rr[H].mean() - rr[L].mean())
    bs = np.array(bs); ci = np.percentile(bs, [2.5, 97.5])
    p = 2 * min((bs <= 0).mean(), (bs >= 0).mean())
    mh = np.isfinite(v) & hold
    dh = a['ret'][mh & (v >= q3)].mean() - a['ret'][mh & (v <= q1)].mean() \
         if (mh & (v >= q3)).sum() > 10 and (mh & (v <= q1)).sum() > 10 else np.nan
    ex = mo != '2025-10'
    de = a['ret'][m & ex & (v >= q3)].mean() - a['ret'][m & ex & (v <= q1)].mean()
    print('{:28s} {:>8,} {:>+9.2f}% {:>+9.2f}% [{:+7.2f},{:+7.2f}] {:>+9.2f}%'.format(
        label, m.sum(), a['ret'][hi_m].mean(), a['ret'][lo_m].mean(), ci[0], ci[1], dh))
    res.append(dict(key=key, label=label, d=d, ci=ci, p=p, dh=dh, de=de, q1=q1, q3=q3))

# BH-FDR
valid = [(i, r['p']) for i, r in enumerate(res) if r]
valid.sort(key=lambda z: z[1]); mtot = len(valid); sig = set()
for rank, (i, p) in enumerate(valid, 1):
    if p <= 0.10 * rank / mtot:
        sig = set(j for j, _ in valid[:rank])

print()
print('=' * 104)
print('기준별 통과 (5개 전부 충족해야 채택)')
print('=' * 104)
print('{:28s} {:^7} {:^7} {:^8} {:^9} {:^7}  {}'.format('특징', '①FDR', '②봉인', '③10월', '④크기15%p', '⑤단조', '판정'))
print('-' * 104)
npass = 0
for i, r in enumerate(res):
    if not r: continue
    v = a[r['key']]; m = np.isfinite(v) & disc
    qs = np.percentile(v[m], [20, 40, 60, 80])
    means = []
    edges = [-np.inf] + list(qs) + [np.inf]
    for k in range(5):
        mm = m & (v > edges[k]) & (v <= edges[k+1])
        means.append(a['ret'][mm].mean() if mm.sum() > 20 else np.nan)
    diffs = np.diff([x for x in means if np.isfinite(x)])
    mono = bool(np.all(diffs > 0) or np.all(diffs < 0))
    c1 = i in sig
    c2 = np.isfinite(r['dh']) and np.sign(r['dh']) == np.sign(r['d'])
    c3 = np.sign(r['de']) == np.sign(r['d'])
    c4 = abs(r['d']) >= 15.0
    ok = all([c1, c2, c3, c4, mono])
    if ok: npass += 1
    f = lambda b: '  O  ' if b else '  X  '
    print('{:28s} {:^7} {:^7} {:^8} {:^9} {:^7}  {}'.format(
        r['label'], f(c1), f(c2), f(c3), f(c4), f(mono),
        '★채택★' if ok else '기각'))
    print('    5분위 평균: ' + ' '.join('{:+.1f}'.format(x) if np.isfinite(x) else '  NA' for x in means))
print()
print('통과: {}/3'.format(npass))
