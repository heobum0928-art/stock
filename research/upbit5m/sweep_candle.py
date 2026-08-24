"""캔들 형태/미시구조 계열 특징 스윕 (탐색 반쪽 'disc'만 사용).

규칙:
- 수익률/비용/연속성 계산은 전부 lib.py 함수만 사용 (fwd_returns/short_of/evaluate).
- 거래가 실제로 있었던 봉만 대상 (h>l AND v>0).
- 격자를 먼저 전부 정의하고 전량 실행한 뒤 결과를 그대로 보고.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib
import numpy as np

BAR_MS = lib.BAR_MS
HOR = ['1h', '4h', '12h', '24h', '48h']

# ---------------------------------------------------------------- 특징 계산
def contig_back(t, k):
    """i 봉 기준 직전 k봉까지 5분 간격으로 연속인가."""
    n = len(t)
    ok = np.zeros(n, bool)
    if n > k:
        ok[k:] = (t[k:] - t[:n-k]) == k*BAR_MS
    return ok


def trailing_mean(x, w):
    """직전 w봉(현재 봉 제외)의 평균. 앞쪽은 nan."""
    n = len(x)
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x, nan=0.0))])
    out = np.full(n, np.nan)
    if n > w:
        out[w:] = (cs[n-0:] if False else (cs[w:n] - cs[0:n-w]))/w
    # 위 슬라이스: out[w:] 길이 n-w, cs[w:n]-cs[0:n-w] 는 [0..w-1],[1..w] ... 직전 w봉
    return out


def features(d):
    o, h, l, c, v, qv, t = (d['o'].astype(np.float64), d['h'].astype(np.float64),
                            d['l'].astype(np.float64), d['c'].astype(np.float64),
                            d['v'].astype(np.float64), d['qv'].astype(np.float64), d['t'])
    n = len(t)
    rng = h - l
    traded = (rng > 0) & (v > 0) & (c > 0) & (o > 0)
    safe = np.where(rng > 0, rng, np.nan)

    body = c - o
    absb = np.abs(body)
    uw = h - np.maximum(o, c)
    lw = np.minimum(o, c) - l

    f = {}
    f['traded'] = traded
    f['br'] = absb/safe                     # 몸통/전체범위
    f['uwr'] = uw/safe                      # 윗꼬리 비율
    f['lwr'] = lw/safe                      # 아랫꼬리 비율
    f['cpos'] = (c - l)/safe                # 봉 내 종가 위치
    f['ret'] = (c/np.where(o > 0, o, np.nan) - 1.0)*100.0   # 봉 수익률 %
    f['bull'] = body > 0
    f['bear'] = body < 0

    # 갭: 이번 봉 시가 vs 직전 봉 종가 (직전 봉과 연속일 때만)
    c1 = np.full(n, np.nan); c1[1:] = c[:-1]
    gap = (o/c1 - 1.0)*100.0
    gap[~contig_back(t, 1)] = np.nan
    f['gap'] = gap

    # 직전 봉 수익률 (연속일 때만)
    p1 = np.full(n, np.nan); p1[1:] = f['ret'][:-1]
    p1[~contig_back(t, 1)] = np.nan
    f['pret'] = p1

    # 상대 캔들 크기: (h-l)/c 를 직전 96봉 평균으로 나눔
    nr = rng/np.where(c > 0, c, np.nan)
    base = trailing_mean(nr, 96)
    base[~contig_back(t, 96)] = np.nan
    f['relrng'] = nr/np.where(base > 0, base, np.nan)

    # 상대 거래대금
    qbase = trailing_mean(qv, 96)
    qbase[~contig_back(t, 96)] = np.nan
    f['relqv'] = qv/np.where(qbase > 0, qbase, np.nan)

    # 연속 양봉/음봉 카운트 (연속성 요구)
    up = (body > 0); dn = (body < 0)
    cu = np.zeros(n, np.int16); cd = np.zeros(n, np.int16)
    c1ok = contig_back(t, 1)
    for i in range(n):
        if up[i]:
            cu[i] = (cu[i-1] if (i > 0 and c1ok[i]) else 0) + 1
        if dn[i]:
            cd[i] = (cd[i-1] if (i > 0 and c1ok[i]) else 0) + 1
    f['cu'] = cu
    f['cd'] = cd

    # 최근 5봉 양봉 개수 (연속 5봉일 때만 유효)
    up5 = np.full(n, np.nan)
    if n >= 5:
        s = np.zeros(n)
        u = up.astype(np.float64)
        cs = np.concatenate([[0.0], np.cumsum(u)])
        s[4:] = cs[5:] - cs[:n-4]
        up5[4:] = s[4:]
    up5[~contig_back(t, 4)] = np.nan
    f['up5'] = up5

    # 3봉 누적 수익률 (종가 대 3봉전 종가)
    c3 = np.full(n, np.nan); c3[3:] = c[:n-3]
    r3 = (c/c3 - 1.0)*100.0
    r3[~contig_back(t, 3)] = np.nan
    f['r3'] = r3
    return f


# ---------------------------------------------------------------- 격자 정의
def build_conditions(f):
    """이름 -> bool 배열. NaN 은 자동으로 False."""
    br, uwr, lwr, cpos = f['br'], f['uwr'], f['lwr'], f['cpos']
    ret, gap, pret = f['ret'], f['gap'], f['pret']
    relrng, relqv, cu, cd, up5, r3 = f['relrng'], f['relqv'], f['cu'], f['cd'], f['up5'], f['r3']
    bull, bear = f['bull'], f['bear']
    C = {}

    def put(name, arr):
        C[name] = np.nan_to_num(arr.astype(np.float64), nan=0.0).astype(bool) if arr.dtype != bool else arr

    # A. 몸통/전체 비율
    for th in (0.7, 0.8, 0.9):
        put(f'body_ratio>={th}', br >= th)
        put(f'body_ratio>={th} & 양봉', (br >= th) & bull)
        put(f'body_ratio>={th} & 음봉', (br >= th) & bear)
    for th in (0.05, 0.10, 0.20):
        put(f'도지 body_ratio<={th}', br <= th)

    # B. 윗꼬리
    for th in (0.5, 0.6, 0.7, 0.8):
        put(f'윗꼬리>={th}', uwr >= th)
    put('윗꼬리>=0.6 & 몸통<=0.3 (슈팅스타)', (uwr >= 0.6) & (br <= 0.3))
    put('윗꼬리>=0.6 & 상대크기>=3', (uwr >= 0.6) & (relrng >= 3))
    put('윗꼬리>=0.6 & 상대거래대금>=3', (uwr >= 0.6) & (relqv >= 3))

    # C. 아랫꼬리
    for th in (0.5, 0.6, 0.7, 0.8):
        put(f'아랫꼬리>={th}', lwr >= th)
    put('아랫꼬리>=0.6 & 몸통<=0.3 (해머)', (lwr >= 0.6) & (br <= 0.3))
    put('아랫꼬리>=0.6 & 상대크기>=3', (lwr >= 0.6) & (relrng >= 3))
    put('아랫꼬리>=0.6 & 상대거래대금>=3', (lwr >= 0.6) & (relqv >= 3))

    # D. 종가 위치
    for th in (0.05, 0.10, 0.20):
        put(f'종가위치<={th}', cpos <= th)
    for th in (0.80, 0.90, 0.95):
        put(f'종가위치>={th}', cpos >= th)

    # E. 갭
    for th in (0.5, 1.0, 2.0):
        put(f'갭>=+{th}%', gap >= th)
        put(f'갭<=-{th}%', gap <= -th)

    # F. 장대봉 (상대 크기)
    for th in (3.0, 5.0, 8.0):
        put(f'상대크기>={th}', relrng >= th)
        put(f'상대크기>={th} & 양봉', (relrng >= th) & bull)
        put(f'상대크기>={th} & 음봉', (relrng >= th) & bear)

    # G. 봉 수익률 (장대양봉/장대음봉 절대기준)
    for th in (3.0, 5.0, 10.0):
        put(f'봉수익률>=+{th}%', ret >= th)
        put(f'봉수익률<=-{th}%', ret <= -th)
    put('봉수익률>=+5% & 몸통>=0.8', (ret >= 5) & (br >= 0.8))
    put('봉수익률<=-5% & 몸통>=0.8', (ret <= -5) & (br >= 0.8))

    # H. 연속 패턴
    for k in (3, 5, 7):
        put(f'연속양봉>={k}', cu >= k)
        put(f'연속음봉>={k}', cd >= k)
    put('최근5봉중 양봉5', up5 >= 5)
    put('최근5봉중 양봉0', up5 <= 0)

    # I. 반전 패턴
    put('직전봉<=-3% & 이번봉>=+1%', (pret <= -3) & (ret >= 1))
    put('직전봉<=-5% & 이번봉>=+1%', (pret <= -5) & (ret >= 1))
    put('직전봉>=+3% & 이번봉<=-1%', (pret >= 3) & (ret <= -1))
    put('직전봉>=+5% & 이번봉<=-1%', (pret >= 5) & (ret <= -1))
    put('직전봉<=-3% & 이번봉 아랫꼬리>=0.5', (pret <= -3) & (lwr >= 0.5))
    put('직전봉>=+3% & 이번봉 윗꼬리>=0.5', (pret >= 3) & (uwr >= 0.5))

    # J. 3봉 누적 + 형태
    for th in (5.0, 10.0):
        put(f'3봉누적>=+{th}%', r3 >= th)
        put(f'3봉누적<=-{th}%', r3 <= -th)
    put('3봉누적>=+10% & 윗꼬리>=0.5', (r3 >= 10) & (uwr >= 0.5))
    put('3봉누적<=-10% & 아랫꼬리>=0.5', (r3 <= -10) & (lwr >= 0.5))

    # K. 마루보즈 + 거래대금
    put('마루보즈양봉 몸통>=0.95', (br >= 0.95) & bull)
    put('마루보즈음봉 몸통>=0.95', (br >= 0.95) & bear)
    put('도지<=0.1 & 상대거래대금>=5', (br <= 0.1) & (relqv >= 5))
    put('상대거래대금>=10 & 양봉', (relqv >= 10) & bull)
    put('상대거래대금>=10 & 음봉', (relqv >= 10) & bear)
    put('상대거래대금>=10 & 종가위치<=0.2', (relqv >= 10) & (cpos <= 0.2))
    put('상대거래대금>=10 & 종가위치>=0.8', (relqv >= 10) & (cpos >= 0.8))
    return C


# ---------------------------------------------------------------- 실행
def main():
    syms = lib.symbols()
    names = None
    acc_cond, acc_ret, acc_t = None, None, []
    n_bar_all = 0
    for s in syms:
        d = lib.load(s)
        n_bar_all += len(d['t'])
        f = features(d)
        mask, rets = lib.fwd_returns(d, 'disc')
        base = mask & f['traded']
        anyfin = np.zeros(len(d['t']), bool)
        for k in HOR:
            anyfin |= np.isfinite(rets[k])
        keep = base & anyfin
        if keep.sum() == 0:
            continue
        C = build_conditions(f)
        if names is None:
            names = list(C.keys())
            acc_cond = {nm: [] for nm in names}
            acc_ret = {k: [] for k in HOR}
        for nm in names:
            acc_cond[nm].append(C[nm][keep])
        for k in HOR:
            acc_ret[k].append(rets[k][keep].astype(np.float32))
        acc_t.append(d['t'][keep])

    cond = {nm: np.concatenate(acc_cond[nm]) for nm in names}
    ret = {k: np.concatenate(acc_ret[k]).astype(np.float64) for k in HOR}
    ts = np.concatenate(acc_t)
    N = len(ts)
    print(f'전체 봉 {n_bar_all}, 평가 대상(거래발생 & disc & 수익률유효) {N}', flush=True)

    rows = []
    tested = 0
    dens_drop = set()
    for nm in names:
        sig = cond[nm]
        fire = sig.sum()/N
        if fire >= 0.10:
            dens_drop.add(nm)
            continue
        for k in HOR:
            for side in ('롱', '숏'):
                r = ret[k] if side == '롱' else lib.short_of(ret[k])
                res = lib.evaluate(sig, r, ts)
                tested += 1
                if not res['ok']:
                    continue
                rows.append(dict(name=nm, side=side, hor=k, fire=fire, **res))

    print(f'검정한 총 조합 수: {tested} (조건 {len(names)}개 x 지평 {len(HOR)} x 방향 2, '
          f'밀도>=10%로 사전 제외된 조건 {len(dens_drop)}개)', flush=True)

    # 기준선(무조건 진입) — 신호가 아니라 대조군. 위 격자에는 포함되지 않는다.
    allsig = np.ones(N, bool)
    baseline = {}
    for k in HOR:
        for side in ('롱', '숏'):
            r = ret[k] if side == '롱' else lib.short_of(ret[k])
            baseline[(k, side)] = lib.evaluate(allsig, r, ts)

    good = [r for r in rows if r['mean'] > 0 and r['n'] >= 500 and r['sign_stable']]
    good.sort(key=lambda x: -x['mean'])
    top = good[:15]

    lines = []
    lines.append('# 캔들 형태/미시구조 계열 스윕 결과 (upbit 5분봉, disc 반쪽)\n')
    lines.append(f'- 데이터: 239종목, 전체 봉 {n_bar_all:,}개')
    lines.append(f'- **거래 발생 봉 필터 적용**: `h>l AND v>0 AND o>0 AND c>0` (h=l=o=c 무거래 봉 제외). '
                 f'분모 0 방어를 위해 (h-l)=0 인 봉은 모든 비율 특징에서 NaN 처리 후 False.')
    lines.append(f'- 평가 대상 표본 풀: {N:,}봉 (disc 구간 + 거래발생 + 유효 순수익률)')
    lines.append(f'- 수익률/비용/연속성: `lib.fwd_returns(d,\'disc\')`, `lib.short_of`, `lib.evaluate`만 사용. '
                 f'`hold` 미호출.')
    lines.append(f'- 조건 {len(names)}개 x 지평 5 x 방향 2 = **검정한 총 조합 수 {tested}** '
                 f'(발동 밀도 >=10% 로 사전 제외된 조건 {len(dens_drop)}개는 검정에서 제외)')
    lines.append(f'- 채택 기준: 평균>0, n>=500, 부호유지(sign_stable)=True. 평균 내림차순 상위 15개.\n')
    if dens_drop:
        lines.append('제외된 고밀도 조건: ' + ', '.join(sorted(dens_drop)) + '\n')

    lines.append('| 특징 정의(재현 가능하게 정확히) | 방향 | 지평 | n | 평균% | 중앙% | 승률% | 최대기여일제외 평균% | 부호유지 |')
    lines.append('|---|---|---|---|---:|---:|---:|---:|---|')
    if not top:
        lines.append('| 조건 충족 0개 | | | | | | | | |')
    for r in top:
        lines.append(f"| {r['name']} | {r['side']} | {r['hor']} | {r['n']} | {r['mean']:.3f} | "
                     f"{r['median']:.3f} | {r['win']:.1f} | {r['mean_ex_topday']:.3f} | {r['sign_stable']} |")
    lines.append('')
    lines.append(f'- 채택 기준 통과 개수: {len(good)}개 (표시는 상위 {len(top)}개)')
    lines.append('')
    lines.append('## 대조군 — 무조건 진입 기준선 (신호 아님, 격자에 미포함)')
    lines.append('')
    lines.append('| 지평 | 방향 | n | 평균% | 중앙% | 승률% |')
    lines.append('|---|---|---:|---:|---:|---:|')
    for k in HOR:
        for side in ('롱', '숏'):
            b = baseline[(k, side)]
            lines.append(f"| {k} | {side} | {b['n']} | {b['mean']:.3f} | {b['median']:.3f} | {b['win']:.1f} |")
    lines.append('')
    lines.append('상위 표의 신호는 반드시 같은 지평·같은 방향의 이 기준선과 비교해서 읽어야 한다.')

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result_candle.md')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
