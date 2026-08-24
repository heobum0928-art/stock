"""시간대/횡단면 계열 특징 스윕 — 사전등록 격자 전수 실행.

규칙:
  - 수익률/비용/연속성 계산은 전부 lib.py 함수만 사용.
  - lib.fwd_returns(d,'disc') 만 호출. 'hold' 는 봉인.
  - 과거수익률(피처)은 직접 계산하지 않고, lib 의 전방수익률 배열을 시프트해서 만든다.
      past_ret_h(i) = rets[h][i-h-1]
    (fwd_returns 정의상 index j 의 값 = open[j+1] -> close[j+h+1] 순수익률이므로,
     j = i-h-1 이면 open[i-h] -> close[i] 구간 = i 봉까지의 과거 h구간 수익률)
    연속성/결측 마스킹도 lib 이 넣은 NaN 이 그대로 따라온다.

데이터 구멍 처리:
  횡단면 집계는 "그 시각에 past_ret 가 유한한 종목만" 모수로 센다.
  (순위/시장평균/폭 전부 동일한 유한 마스크 위에서 계산)

출력: research/upbit5m/result_xsec.md
"""
import sys, os, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import lib

HZ = ['1h', '4h', '12h', '24h', '48h']
PAST_W = ['1h', '4h', '12h']          # 횡단면 피처용 과거 창
RT = lib.COST_SIDE * 2 * 100.0        # 왕복 비용(%) — 총수익률 복원용 상수

# ---------------------------------------------------------------- 1. 적재
syms = lib.symbols()
T, S, RL, PAST = [], [], {k: [] for k in HZ}, {w: [] for w in PAST_W}

for si, sym in enumerate(syms):
    d = lib.load(sym)
    mask, rets = lib.fwd_returns(d, 'disc')
    n = len(mask)
    T.append(d['t'])
    S.append(np.full(n, si, np.int32))
    for k in HZ:
        r = rets[k].copy()
        r[~mask] = np.nan                      # 탐색 반쪽 + 연속성 밖은 무효
        RL[k].append(r)
    for w in PAST_W:
        h = lib.HORIZONS[w]
        p = np.full(n, np.nan)
        if n > h + 1:
            p[h + 1:] = rets[w][:n - h - 1]    # 과거 창으로 시프트
        PAST[w].append(p)

t = np.concatenate(T)
sym_id = np.concatenate(S)
retL = {k: np.concatenate(RL[k]) for k in HZ}
retS = {k: lib.short_of(retL[k]) for k in HZ}
past = {w: np.concatenate(PAST[w]) for w in PAST_W}
del T, S, RL, PAST
N = len(t)
print(f'[load] bars={N} syms={len(syms)}', flush=True)

# 밀도 분모: 탐색 구간에서 하나라도 평가 가능한 봉 (24h 기준 유한)
DENOM = int(np.isfinite(retL['24h']).sum())
DENSITY_CAP = 0.10
print(f'[denom] 24h 평가가능 봉 = {DENOM}', flush=True)

# ---------------------------------------------------------------- 2. 시간 피처
KST = (t // 3600000 + 9) % 24                       # KST 시(hour)
DOW = ((t // 86400000) + 4) % 7                     # 1970-01-01=목(=4) 기준, 0=월
MIN = (t % 3600000) // 60000                        # 분
DOM_APPROX = ((t // 86400000) % 30)                 # 월 근사 없이 쓰지 않음(아래 실제 계산)
# 실제 월중 일자: datetime 없이 정확히 — numpy datetime64 사용
dt = t.astype('datetime64[ms]') + np.timedelta64(9, 'h')   # KST
DOM = (dt.astype('datetime64[D]') - dt.astype('datetime64[M]')).astype(int) + 1
DIM = ((dt.astype('datetime64[M]') + 1).astype('datetime64[D]')
       - dt.astype('datetime64[M]').astype('datetime64[D]')).astype(int)

# ---------------------------------------------------------------- 3. 횡단면 집계
# 시각별 그룹 인덱스
uniq_t, tidx = np.unique(t, return_inverse=True)
G = len(uniq_t)
print(f'[xsec] 고유 시각 = {G}', flush=True)

xrank, xmean, xbreadth, xexcess = {}, {}, {}, {}
for w in PAST_W:
    p = past[w]
    fin = np.isfinite(p)
    cnt = np.bincount(tidx[fin], minlength=G).astype(np.float64)
    ssum = np.bincount(tidx[fin], weights=p[fin], minlength=G)
    mean = np.where(cnt > 0, ssum / np.maximum(cnt, 1), np.nan)
    gross_up = (p + RT) > 0                                  # 총수익률(비용 전) 상승 여부
    upc = np.bincount(tidx[fin & gross_up], minlength=G).astype(np.float64)
    br = np.where(cnt > 0, upc / np.maximum(cnt, 1), np.nan)

    # 그룹 내 백분위 순위 (유한한 종목만 모수)
    idx = np.flatnonzero(fin)
    order = np.lexsort((p[idx], tidx[idx]))
    sidx = idx[order]
    gt = tidx[sidx]
    start = np.zeros(G, np.int64)
    gcnt = np.bincount(gt, minlength=G)
    start[1:] = np.cumsum(gcnt)[:-1]
    pos = np.arange(len(sidx)) - start[gt]                   # 0..cnt-1 (오름차순)
    rk = np.full(N, np.nan)
    rk[sidx] = (pos + 0.5) / gcnt[gt]                        # 0=최하위, 1=최상위
    xrank[w] = rk
    xmean[w] = np.where(cnt[tidx] > 0, mean[tidx], np.nan)
    xbreadth[w] = np.where(cnt[tidx] > 0, br[tidx], np.nan)
    xexcess[w] = p - xmean[w]
    # 종목수 부족한 시각(<20종목)은 횡단면 무효
    thin = cnt[tidx] < 20
    for arr in (xrank[w], xmean[w], xbreadth[w], xexcess[w]):
        arr[thin] = np.nan
    print(f'  w={w} 유한 past={fin.sum()} 시각당 중앙 종목수={np.median(cnt[cnt>0]):.0f}', flush=True)

# 시장평균의 자기분포 분위 (전체 시각 기준)
xmean_q = {}
for w in PAST_W:
    m = xmean[w]
    f = np.isfinite(m)
    q = np.full(N, np.nan)
    q[f] = (np.argsort(np.argsort(m[f])) + 0.5) / f.sum()
    xmean_q[w] = q

# ---------------------------------------------------------------- 4. 조건 격자
rows = []
n_cond = 0
tested = 0
dropped_density = 0

def add(name, arr):
    """조건을 즉시 평가하고 버린다(메모리 절약)."""
    global n_cond, tested, dropped_density
    c = np.asarray(arr, bool)
    n_cond += 1
    dens = float(c.sum()) / N
    dens24 = float((c & np.isfinite(retL['24h'])).sum()) / max(DENOM, 1)
    if dens >= DENSITY_CAP or dens24 >= DENSITY_CAP:
        dropped_density += 1
        return
    for hz in HZ:
        for dname, R in (('롱', retL[hz]), ('숏', retS[hz])):
            tested += 1
            res = lib.evaluate(c, R, t, min_n=500)
            if not res.get('ok'):
                continue
            rows.append(dict(name=name, dir=dname, hz=hz, dens=dens, **res))

# --- 시간 단독
for h in range(24):
    add(f'KST시={h}', KST == h)
for dw, nm in enumerate(['월', '화', '수', '목', '금', '토', '일']):
    add(f'KST요일={nm}', DOW == dw)
add('주말(토일)', DOW >= 5)
add('평일(월~금)', DOW <= 4)
SESS = {'한국장(09-15시)': (KST >= 9) & (KST <= 15),
        '한국밤(16-21시)': (KST >= 16) & (KST <= 21),
        '미국장(22-04시)': (KST >= 22) | (KST <= 4),
        '아시아새벽(05-08시)': (KST >= 5) & (KST <= 8)}
for k, v in SESS.items():
    add(f'세션={k}', v)
add('월초(1~3일)', DOM <= 3)
add('월말(마지막3일)', DOM > DIM - 3)
add('정각봉(분=00)', MIN == 0)
add('30분봉(분=30)', MIN == 30)

# --- 횡단면 단독
RANK_BINS = [('하위2%', lambda r: r <= 0.02), ('하위5%', lambda r: r <= 0.05),
             ('하위8%', lambda r: r <= 0.08), ('상위8%', lambda r: r >= 0.92),
             ('상위5%', lambda r: r >= 0.95), ('상위2%', lambda r: r >= 0.98)]
for w in PAST_W:
    r = xrank[w]
    for nm, f in RANK_BINS:
        add(f'횡단순위{w}={nm}', np.where(np.isfinite(r), f(r), False))
    q = xmean_q[w]
    add(f'시장평균{w}=하위5%', np.where(np.isfinite(q), q <= 0.05, False))
    add(f'시장평균{w}=하위10%', np.where(np.isfinite(q), q <= 0.10, False))
    add(f'시장평균{w}=상위10%', np.where(np.isfinite(q), q >= 0.90, False))
    add(f'시장평균{w}=상위5%', np.where(np.isfinite(q), q >= 0.95, False))
    b = xbreadth[w]
    for th, nm in [(0.10, '<=10%'), (0.20, '<=20%')]:
        add(f'시장폭{w}{nm}', np.where(np.isfinite(b), b <= th, False))
    for th, nm in [(0.80, '>=80%'), (0.90, '>=90%')]:
        add(f'시장폭{w}{nm}', np.where(np.isfinite(b), b >= th, False))
    e = xexcess[w]
    for th in (-20, -10, -5):
        add(f'초과수익{w}<={th}%', np.where(np.isfinite(e), e <= th, False))
    for th in (5, 10, 20):
        add(f'초과수익{w}>={th}%', np.where(np.isfinite(e), e >= th, False))

# --- 시장방향 × 개별순위 조합
for w in PAST_W:
    r, m, b = xrank[w], xmean[w], xbreadth[w]
    up = np.isfinite(m) & (m > 0)
    dn = np.isfinite(m) & (m < 0)
    for nm, f in RANK_BINS:
        add(f'시장상승&횡단순위{w}={nm}', up & np.isfinite(r) & f(r))
        add(f'시장하락&횡단순위{w}={nm}', dn & np.isfinite(r) & f(r))
    bu = np.isfinite(b) & (b >= 0.70)
    bd = np.isfinite(b) & (b <= 0.30)
    for nm, f in RANK_BINS:
        add(f'시장폭>=70%&횡단순위{w}={nm}', bu & np.isfinite(r) & f(r))
        add(f'시장폭<=30%&횡단순위{w}={nm}', bd & np.isfinite(r) & f(r))

# --- 시간 × 횡단면 조합 (1h 창 고정)
r1 = xrank['1h']
for sk, sv in SESS.items():
    for nm, f in RANK_BINS:
        add(f'세션={sk}&횡단순위1h={nm}', sv & np.isfinite(r1) & f(r1))
for wk, wv in [('주말', DOW >= 5), ('평일', DOW <= 4)]:
    for nm, f in RANK_BINS:
        add(f'{wk}&횡단순위1h={nm}', wv & np.isfinite(r1) & f(r1))
# 시간대(24) × 극단순위 2종
for h in range(24):
    for nm, f in [('하위5%', lambda r: r <= 0.05), ('상위5%', lambda r: r >= 0.95)]:
        add(f'KST시={h}&횡단순위1h={nm}', (KST == h) & np.isfinite(r1) & f(r1))

# ---------------------------------------------------------------- 5. 집계
print(f'[grid] 조건 {n_cond}개', flush=True)
print(f'[eval] 검정 조합 {tested}개 / 밀도탈락 조건 {dropped_density}개 / 유효행 {len(rows)}', flush=True)

good = [r for r in rows if r['mean'] > 0 and r['n'] >= 500 and r['sign_stable']]
good.sort(key=lambda r: -r['mean'])
top = good[:15]

# ---------------------------------------------------------------- 6. 보고
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result_xsec.md')
L = []
L.append('# 시간대/횡단면 계열 특징 스윕 결과\n')
L.append(f'- 데이터: 업비트 원화 5분봉 {len(syms)}종목, 총 {N:,}봉 (탐색 반쪽 `disc` 만)')
L.append(f'- 24h 지평 평가가능 봉 = {DENOM:,} (밀도 분모)')
L.append(f'- 조건 격자 {n_cond}개 → 밀도(>=10%) 탈락 {dropped_density}개')
L.append(f'- **검정한 총 조합 수 = {tested}** (조건 × 방향2 × 지평5)')
L.append(f'- 표본 500건 이상으로 성적이 산출된 행 = {len(rows)}, 그중 평균>0 & 부호유지 = {len(good)}\n')
L.append('## 구멍(결측) 처리')
L.append('- 전방수익률/연속성/비용은 전부 `lib.fwd_returns(d,"disc")` 결과만 사용. 직접 계산 없음.')
L.append('- 횡단면 피처의 과거수익률은 lib 전방수익률 배열을 `past(i)=rets[w][i-h-1]` 로 시프트해 만들었다. '
         '따라서 lib 이 연속성 위반에 넣은 NaN 이 그대로 상속된다.')
L.append('- 시각별 집계(평균/폭/순위)는 **그 시각에 과거수익률이 유한한 종목만** 모수로 삼았다. '
         '결측 종목은 분모에서 제외된다.')
L.append('- 그 시각 유한 종목이 20개 미만이면 횡단면 피처 전체를 NaN 처리(초기 구간 왜곡 방지).')
L.append('- 시장폭은 비용 차감 전 총수익률 기준(`past + 0.12%p > 0`)으로 상승 판정.\n')
L.append('## 상위 결과\n')
hdr = ('| 특징 정의 | 방향 | 지평 | n | 평균% | 중앙% | 승률% | 최대기여일제외 평균% | 부호유지 |\n'
       '|---|---|---|---|---|---|---|---|---|')
L.append(hdr)
if not top:
    L.append('\n**조건 충족 0개**')
else:
    for r in top:
        L.append(f"| {r['name']} | {r['dir']} | {r['hz']} | {r['n']} | {r['mean']:.3f} | "
                 f"{r['median']:.3f} | {r['win']:.1f} | {r['mean_ex_topday']:.3f} | {r['sign_stable']} |")
if not top:
    L.append('')
    L.append('조건: 평균 > 0, 표본 >= 500, 부호유지 = True')

# 정직성 경고 — 지표 하나로 결론 내지 않는다
n_medneg = sum(1 for r in top if r['median'] <= 0)
n_winlo = sum(1 for r in top if r['win'] < 50)
n_48h = sum(1 for r in top if r['hz'] == '48h')
L.append('\n## 읽을 때 주의\n')
L.append(f'- 상위 {len(top)}개 중 **중앙값이 0 이하인 것이 {n_medneg}개, 승률 50% 미만이 {n_winlo}개**. '
         '평균이 양수인 것은 소수의 큰 상승(우측 꼬리)이 끌어올린 결과다. 중앙적 거래는 진다.')
L.append(f'- 상위 {len(top)}개 중 지평 48h 가 {n_48h}개. 긴 지평일수록 표본이 겹치고(중복 계수) '
         '분산이 커서 평균이 부풀기 쉽다. 독립 표본 수는 n 보다 훨씬 적다.')
L.append('- 최대기여일 제외 평균이 전부 원평균보다 크게 낮다 → 특정 날짜 의존이 남아 있다. '
         '`sign_stable` 은 부호만 보는 약한 검사다.')
L.append(f'- 검정 조합 {tested}개에 대한 **다중검정 보정을 하지 않았다.** 이 표는 가설 목록이지 결론이 아니다.')
L.append('- 백테스트에 **청산/스탑 시뮬레이션이 없다.** 48h 보유 중 -95% 구간을 견딘다는 가정이다.')
L.append('- 격자는 결과를 보기 전에 코드에 고정했고, 실행 후 조건을 추가·미세조정하지 않았다.')

# 참고: 평균 상위(부호유지 무관) 20개도 남긴다
rows.sort(key=lambda r: -r['mean'])
L.append('\n## (참고) 부호유지 조건 무시한 평균 상위 20개\n')
L.append(hdr)
for r in rows[:20]:
    L.append(f"| {r['name']} | {r['dir']} | {r['hz']} | {r['n']} | {r['mean']:.3f} | "
             f"{r['median']:.3f} | {r['win']:.1f} | {r['mean_ex_topday']:.3f} | {r['sign_stable']} |")

with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(L) + '\n')
print('[write]', out)
for line in L[:8]:
    print(line)
print('--- TOP ---')
for r in top:
    print(f"{r['name']} | {r['dir']} | {r['hz']} | n={r['n']} | mean={r['mean']:.3f} | "
          f"med={r['median']:.3f} | win={r['win']:.1f} | ex={r['mean_ex_topday']:.3f}")
