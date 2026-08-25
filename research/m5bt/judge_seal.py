"""PREREG_SWEEP_BINANCE.md 5절 판정 — seal2_hold.pkl / seal2_disc.pkl 을 읽어 7개 기준 계산.
봉인 개봉 자체는 open_seal2.py hold 가 한다. 이 파일은 그 산출물을 판정만 한다."""
import pickle, numpy as np, datetime as dt

disc = pickle.load(open('seal2_disc.pkl','rb'))
hold = pickle.load(open('seal2_hold.pkl','rb'))
rng = np.random.default_rng(20260826)

def day_block_boot(r, tt, n=4000):
    """일-블록 부트스트랩: 같은 날 여러 종목이 동시에 움직이므로 날짜 단위로 재표집."""
    day = tt // 86400000
    ud = np.unique(day)
    idx = {u: np.flatnonzero(day == u) for u in ud}
    out = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), len(ud))
        ii = np.concatenate([idx[ud[p]] for p in pick])
        out.append(r[ii].mean())
    return np.array(out)

rows = []
for k, (d, h) in enumerate(zip(disc, hold)):
    if d is None or h is None:
        rows.append(None); continue
    r = h['r']; tt = h['tt']
    bs = day_block_boot(r, tt)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    p = 2 * min((bs <= 0).mean(), (bs >= 0).mean())
    mo = np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in tt])
    oct_r = r[mo == '2025-10']
    rows.append(dict(nm=h['nm'], n=len(r), mean=r.mean(), lo=lo, hi=hi, p=p,
                     ex=h['ex'], same=h['same'], mtot=h['mtot'], exo=h['exo'],
                     oct=oct_r.mean() if len(oct_r) else np.nan, octn=len(oct_r),
                     dmean=d['r'].mean()))

# BH-FDR (5개 동시, q=0.10)
valid = [(i, x['p']) for i, x in enumerate(rows) if x]
valid.sort(key=lambda z: z[1])
m = len(valid); q = 0.10
sig = set()
for rank, (i, p) in enumerate(valid, 1):
    if p <= q * rank / m:
        sig = set(j for j, _ in valid[:rank])

print('=' * 118)
print('PREREG_SWEEP_BINANCE.md 5절 판정 — 홀드아웃 (봉인 개봉 결과)')
print('=' * 118)
hdr = ('후보', 'n', '홀드평균', '부트95%CI', 'p', 'FDR', '기여일제외', '월', '10월제외', '10월만', '탐색부호')
print('{:26s} {:>7} {:>8} {:>19} {:>7} {:>5} {:>9} {:>6} {:>9} {:>9} {:>7}'.format(*hdr))
print('-' * 118)
for i, x in enumerate(rows):
    if not x:
        print('  (표본 0)'); continue
    print('{:26s} {:>7,} {:>+7.3f} [{:+6.2f},{:+6.2f}] {:>7.3f} {:>5} {:>+8.3f} {:>4}/{:<2} {:>+8.3f} {:>+8.2f} {:>+6.3f}'.format(
        x['nm'][:26], x['n'], x['mean'], x['lo'], x['hi'], x['p'],
        'O' if i in sig else 'X', x['ex'], x['same'], x['mtot'], x['exo'], x['oct'], x['dmean']))

print()
print('=' * 118)
print('기준별 통과 여부 (7개 전부 충족해야 채택 후보)')
print('=' * 118)
print('{:26s} {:^5} {:^5} {:^5} {:^5} {:^5} {:^5} {:^5}  {}'.format(
    '후보','①>0','②CI','③FDR','④기여일','⑤부호','⑥월8+','⑦10월','판정'))
print('-' * 118)
n_pass = 0
for i, x in enumerate(rows):
    if not x: continue
    c1 = x['mean'] > 0
    c2 = x['lo'] > 0
    c3 = i in sig
    c4 = np.sign(x['ex']) == np.sign(x['mean'])
    c5 = np.sign(x['dmean']) == np.sign(x['mean'])
    c6 = x['same'] >= 8
    c7 = (np.sign(x['exo']) == np.sign(x['mean'])) and not (x['oct'] < -20)
    ok = all([c1,c2,c3,c4,c5,c6,c7])
    if ok: n_pass += 1
    f = lambda b: ' O ' if b else ' X '
    print('{:26s} {:^5} {:^5} {:^5} {:^5} {:^5} {:^5} {:^5}  {}'.format(
        x['nm'][:26], f(c1),f(c2),f(c3),f(c4),f(c5),f(c6),f(c7),
        '★★ 채택후보 ★★' if ok else '기각'))
print()
print('통과: {}/5개'.format(n_pass))
