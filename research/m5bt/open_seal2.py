"""후보 5개 봉인 검정 v2 — 원본 스윕 코드를 그대로 import.

★ 2026-08-25: open_seal.py(v1)는 특징을 재구현했는데 원본과 안 맞아 후보 3·4·5의
   재현이 실패했다. 원인을 원본 코드 대조로 규명:
     - 격자가 스윕마다 다름: 모멘텀 STRIDE=12(1h), 변동성 STRIDE=6(30분),
       거래량은 서브샘플 없이 전봉. v1은 전부 1시간 격자로 통일해버림.
     - 후보4의 rank: 원본은 pandas rolling(8640, min=2000).rank(pct=True) 후
       q8(x*200) 양자화, 임계 lo02='<=4'(=2%), pos48.lo05='<=10'(=5%).
       v1의 rank30()은 48봉 간격 180표본 근사로 완전히 다른 값. pos48도 원값 0.05로 씀.
     - 후보3/5: 원본은 qv를 float64 캐스팅 후 np.divide(where=...)로 0·NaN 방어.
   → 재구현을 버리고 **원본 모듈의 함수를 직접 호출**한다(오늘 반복 확인된 교훈).

사용법: python open_seal2.py disc   (재현검증 — 탐색 구간에서 원본 수치 재현되는지)
        python open_seal2.py hold   (봉인 개봉 — 단 한 번)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, datetime as dt
import swlib as L
import bsweep_momentum as BM
import bsweep_vol as BV
import bsweep_volume as BQ

HALF = sys.argv[1]
assert HALF in ('disc', 'hold')

# ── 후보 정의: (표시명, 방향, 지평, 출처스윕, 판정함수) ───────────────────────
# 각 판정함수는 원본 스윕의 특징 계산 결과를 받아 bool 배열을 돌려준다.

def sig_c1(d):
    """1. 288봉 저점대비 상승폭 >= +50% (LONG) — 모멘텀 스윕, STRIDE=12"""
    lo = _roll_min(d['l'], 288)
    du = (d['c'] / lo - 1.0) * 100.0
    return du >= 50.0

def sig_c2(d):
    """2. 48봉 저점대비 상승폭 >= +30% (LONG) — 모멘텀 스윕, STRIDE=12"""
    lo = _roll_min(d['l'], 48)
    du = (d['c'] / lo - 1.0) * 100.0
    return du >= 30.0

def _roll_min(x, w):
    return pd.Series(np.asarray(x, float)).rolling(w, min_periods=w).min().to_numpy()

def sig_c3(d):
    """3. max/sum(qv,288) >= 0.7 (SHORT) — 거래량 스윕 build_features 그대로"""
    names, feats = BQ.build_features(d)
    j = names.index('max/sum(qv,288) >= 0.7')
    return feats[:, j]

def sig_c5(d):
    """5. qv/med288 <= 1.2 & 12봉가격 >= +5.0% (LONG) — 거래량 스윕 그대로"""
    names, feats = BQ.build_features(d)
    j = names.index('qv/med288 <= 1.2 & 12봉가격 >= +5.0%')
    return feats[:, j]

def sig_c4(d):
    """4. rv48_o_rv288.lo02 & pos48.lo05 (LONG) — 변동성 스윕 feats_of + q8 그대로.
    원본 임계: RANK_TH lo02 -> le 4 (q8 기준), POS_TH lo05 -> le 10."""
    F = BV.feats_of(d)
    r = F['rv48_o_rv288'].replace([np.inf, -np.inf], np.nan) \
                         .rolling(BV.RANKW, min_periods=BV.RANKMIN).rank(pct=True)
    a = BV.q8(r.values)
    b = BV.q8(F['pos48'].replace([np.inf, -np.inf], np.nan).values)
    return (a <= 4) & (a != 255) & (b <= 10) & (b != 255)

CAND = [
    ('1. 288봉 저점대비 >= +50%',  'LONG',  '48h', 12, sig_c1),
    ('2. 48봉 저점대비 >= +30%',   'LONG',  '48h', 12, sig_c2),
    ('3. 거래대금 집중도 >= 0.7',  'SHORT', '48h',  1, sig_c3),
    ('4. 변동성압축 + 레인지하단', 'LONG',  '48h',  6, sig_c4),
    ('5. 조용 + 1시간 >= +5%',     'LONG',  '48h',  1, sig_c5),
]

acc = [{'r': [], 't': [], 's': []} for _ in CAND]
base = {'r': [], 't': []}
syms = L.symbols(HALF)
print('구간={}  종목 {}개 - 원본 스윕 함수 직접 호출'.format(HALF, len(syms)), flush=True)

for si, sym in enumerate(syms):
    try:
        d = L.load(sym)
    except Exception:
        continue
    n = len(d['t'])
    if n < 9000:
        continue
    m, LO, SH = L.fwd_returns(d, sym)
    for k, (nm, side, hz, stride, fn) in enumerate(CAND):
        arr = LO[hz] if side == 'LONG' else SH[hz]
        try:
            sig = np.asarray(fn(d), bool)
        except Exception as e:
            if si == 0:
                print('  후보{} 계산실패: {}'.format(k + 1, e), flush=True)
            continue
        # 각 후보의 원본 격자를 그대로 적용.
        # ★ 모멘텀(1·2)은 원본이 시각 기준 `(t//BAR)%STRIDE==0`(bsweep_momentum.py:95),
        #   변동성(4)은 배열 위치 기준 `sel[::STRIDE]`(bsweep_vol.py:135)로 서로 다르다.
        #   데이터에 빈 구간이 있으면 둘이 어긋나므로 각각 원본 방식을 그대로 쓴다.
        if stride > 1:
            if k in (0, 1):      # 모멘텀 — 시각 기준
                sel = ((d['t'] // L.BAR) % stride) == 0
            else:                # 변동성 — 배열 위치 기준
                sel = np.zeros(n, bool); sel[::stride] = True
        else:
            sel = np.ones(n, bool)
        ok = m & sel & sig & np.isfinite(arr)
        if ok.any():
            acc[k]['r'].append(arr[ok]); acc[k]['t'].append(d['t'][ok])
            acc[k]['s'].append(np.full(int(ok.sum()), si))
    b = m & np.isfinite(LO['48h'])
    base['r'].append(LO['48h'][b]); base['t'].append(d['t'][b])
    if (si + 1) % 50 == 0:
        print('  {}/{}'.format(si + 1, len(syms)), flush=True)

br = np.concatenate(base['r']); bt = np.concatenate(base['t'])
bmo = np.array([dt.datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m') for x in bt])
print()
print('=' * 108)
print('구간 = {}   종목 {}개'.format('탐색(재현검증)' if HALF == 'disc' else '★★ 봉인 개봉 ★★', len(syms)))
print('=' * 108)
print('기준선 무조건 롱 48h: {:+.3f}%   (10월 제외 {:+.3f}%)   n={:,}'.format(
    br.mean(), br[bmo != '2025-10'].mean(), len(br)))
print()
print('{:28s} {:>9} {:>5} {:>5} {:>8} {:>8} {:>6} {:>9} {:>6} {:>9}'.format(
    '후보', 'n', '종목', '날짜', '평균%', '중앙%', '승률', '기여일제외', '월', '10월제외'))
out = []
for k, (nm, side, hz, stride, _) in enumerate(CAND):
    if not acc[k]['r']:
        print('{:28s}  표본 0'.format(nm)); out.append(None); continue
    r = np.concatenate(acc[k]['r']); tt = np.concatenate(acc[k]['t']); ss = np.concatenate(acc[k]['s'])
    day = (tt // 86400000); ud = np.unique(day)
    mo = np.array([dt.datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m') for x in tt])
    contrib = {u: r[day == u].sum() for u in ud}
    top = max(contrib, key=lambda z: abs(contrib[z]))
    ex = r[day != top]; um = np.unique(mo)
    same = sum(1 for x in um if np.sign(r[mo == x].mean()) == np.sign(r.mean()))
    exo = r[mo != '2025-10']
    print('{:28s} {:>9,} {:>5} {:>5} {:>8.3f} {:>8.3f} {:>6.1f} {:>9.3f} {:>4}/{:<2} {:>9.3f}'.format(
        nm, len(r), len(np.unique(ss)), len(ud), r.mean(), np.median(r), (r > 0).mean() * 100,
        ex.mean() if len(ex) else np.nan, same, len(um), exo.mean() if len(exo) else np.nan))
    out.append(dict(nm=nm, r=r, tt=tt, ss=ss, ex=ex.mean() if len(ex) else np.nan,
                    same=same, mtot=len(um), exo=exo.mean() if len(exo) else np.nan,
                    oct=r[mo == '2025-10'].mean() if (mo == '2025-10').any() else np.nan,
                    octn=int((mo == '2025-10').sum())))

import pickle
pickle.dump(out, open('seal2_%s.pkl' % HALF, 'wb'))
print()
print('저장: seal2_{}.pkl'.format(HALF))
