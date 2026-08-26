"""후보5 규칙의 보유기간별 비교 — 봉인 재개봉이 아니라 이미 계산된 지평을 나란히 본다.
사전등록 6절이 금지한 것은 '결과를 보고 48h를 바꾸는 것'이다. 여기서는 관측만 하고,
채택하려면 별도 사전등록을 새로 써야 한다."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, datetime as dt
import swlib as L
import bsweep_volume as BQ

HALF = sys.argv[1]
HZ = ['1h', '4h', '12h', '24h', '48h']
NAME = 'qv/med288 <= 1.2 & 12봉가격 >= +5.0%'

acc = {h: {'r': [], 't': [], 's': []} for h in HZ}
base = {h: [] for h in HZ}
syms = L.symbols(HALF)
print('구간={} 종목 {}개'.format(HALF, len(syms)), flush=True)
for si, sym in enumerate(syms):
    try:
        d = L.load(sym)
    except Exception:
        continue
    if len(d['t']) < 9000:
        continue
    m, LO, SH = L.fwd_returns(d, sym)
    names, feats = BQ.build_features(d)
    sig = feats[:, names.index(NAME)]
    for h in HZ:
        arr = LO[h]
        ok = m & sig & np.isfinite(arr)
        if ok.any():
            acc[h]['r'].append(arr[ok]); acc[h]['t'].append(d['t'][ok])
            acc[h]['s'].append(np.full(int(ok.sum()), si))
        b = m & np.isfinite(arr)
        base[h].append(arr[b])
    if (si + 1) % 100 == 0:
        print('  {}/{}'.format(si + 1, len(syms)), flush=True)

rng = np.random.default_rng(20260826)
print()
print('=' * 100)
print('후보5 "조용 + 1시간>=+5% -> 롱" 보유기간별 비교 ({})'.format(
    '탐색' if HALF == 'disc' else '★홀드아웃'))
print('=' * 100)
print('{:>6} {:>9} {:>9} {:>9} {:>7} {:>19} {:>7} {:>9}'.format(
    '보유', 'n', '평균%', '기준선%', '우위%p', '부트 95%CI', '승률', '월일치'))
print('-' * 100)
for h in HZ:
    if not acc[h]['r']:
        continue
    r = np.concatenate(acc[h]['r']); tt = np.concatenate(acc[h]['t'])
    br = np.concatenate(base[h])
    mo = np.array([dt.datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m') for x in tt])
    um = np.unique(mo)
    same = sum(1 for x in um if np.sign(r[mo == x].mean()) == np.sign(r.mean()))
    day = tt // 86400000; ud = np.unique(day)
    idx = {u: np.flatnonzero(day == u) for u in ud}
    bs = []
    for _ in range(2000):
        pick = rng.integers(0, len(ud), len(ud))
        ii = np.concatenate([idx[ud[p]] for p in pick])
        bs.append(r[ii].mean())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print('{:>6} {:>9,} {:>+8.3f} {:>+8.3f} {:>+8.3f} [{:+7.2f},{:+7.2f}] {:>6.1f}% {:>6}/{:<2}'.format(
        h, len(r), r.mean(), br.mean(), r.mean() - br.mean(), lo, hi,
        (r > 0).mean() * 100, same, len(um)))
