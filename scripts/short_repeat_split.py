"""prereg #57 PREREG_SHORT_REPEAT.md — 같은 코인의 직전 30일 신호 이력(첫 vs 반복) 분할. 주문 없음."""
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
H = 3600000; DAY = 86400000

order = np.argsort(t0, kind='stable')
cnt = np.zeros(len(a), dtype=int)
hist = {}
for i in order:
    s = sym[i]; t = t0[i]
    cnt[i] = sum(1 for p in hist.get(s, ()) if t - 30 * DAY <= p <= t - 48 * H)
    hist.setdefault(s, []).append(t)

ok = t0 >= t0.min() + 30 * DAY
x = net[ok]; c = cnt[ok]; day = t0[ok] // DAY; sy = sym[ok]
first = c == 0; rep = c >= 1
print(f'이력 확보 {ok.sum()}/{len(a)}  첫 {first.sum()} / 반복 {rep.sum()}')


def st(m):
    v = x[m]
    return (f'n={m.sum()} 평균 {v.mean()*100:+.2f}% 중앙 {np.median(v)*100:+.2f}% 승률 {(v>0).mean()*100:.0f}% '
            f'최악 {v.min()*100:+.0f}% -50%이하 {(v < -0.5).mean()*100:.1f}%')


print('첫 급등  :', st(first))
print('반복 급등:', st(rep))

days = np.unique(day); idx = {dd: np.nonzero(day == dd)[0] for dd in days}
rng = np.random.default_rng(20261011); ds = []
for _ in range(4000):
    sel = np.concatenate([idx[days[p]] for p in rng.integers(0, len(days), len(days))])
    xs = x[sel]; r = rep[sel]; f = first[sel]
    if r.any() and f.any():
        ds.append(xs[r].mean() - xs[f].mean())
lo99, hi99 = np.percentile(ds, [0.5, 99.5]); lo95, hi95 = np.percentile(ds, [2.5, 97.5])
df = x[rep].mean() - x[first].mean()
print(f'차이(반복 − 첫) {df*100:+.2f}%p  99% CI [{lo99*100:+.2f},{hi99*100:+.2f}]  (참고 95% CI [{lo95*100:+.2f},{hi95*100:+.2f}])')

med = np.median(day); half = []
for nm, m in (('전반', day <= med), ('후반', day > med)):
    a1 = x[m & rep]; a2 = x[m & first]
    dd_ = a1.mean() - a2.mean(); half.append(dd_)
    print(f'  {nm}: 반복 {a1.mean()*100:+.2f}%(n={len(a1)}) 첫 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {dd_*100:+.2f}%p')

print('이전 신호 횟수 3구간:')
for nm, m in (('1', c == 1), ('2~3', (c >= 2) & (c <= 3)), ('4+', c >= 4)):
    if m.sum():
        print(f'  {nm}: {st(m)}')

# 같은 종목 안 비교
diffs = []
for s in np.unique(sy):
    m = sy == s
    if (m & first).any() and (m & rep).any():
        diffs.append(x[m & rep].mean() - x[m & first].mean())
diffs = np.array(diffs)
if len(diffs):
    print(f'같은 종목 안 비교: 종목 {len(diffs)}개, 종목별 차이 평균 {diffs.mean()*100:+.2f}%p 중앙 {np.median(diffs)*100:+.2f}%p 양(+) 비율 {(diffs>0).mean()*100:.0f}%')

if first.sum() < 300 or rep.sum() < 300:
    verdict = '판별 불가'
else:
    same = all(np.sign(h) == np.sign(df) for h in half)
    verdict = '성립' if ((lo99 > 0 or hi99 < 0) and same) else '기각'
direction = '반복이 더 나쁨(숏 입장 -)' if df < 0 else '반복이 더 좋음(숏 입장 +)'
print('판정:', verdict, '| 방향:', direction)
