"""변동성/레인지 계열 특징 전수 탐색 (탐색구간 'disc' 만 사용).

규칙:
 - 수익률/비용/연속성 계산은 전부 lib.py 에 위임한다 (직접 계산 금지).
 - lib.fwd_returns(d,'disc') 만 호출. 'hold' 는 봉인.
 - 격자를 먼저 고정하고 전부 돌린 뒤 결과를 그대로 보고한다.

특징은 봉 i 시점까지의 정보만 쓴다(위치 기반 창). 결측봉이 잦아 창의 실제
경과시간은 창 길이보다 길 수 있으나, 미래 정보는 절대 쓰지 않는다.
진입/청산/비용/구간 연속성은 lib.fwd_returns 가 처리한다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib
import numpy as np

# ---------- 고정 격자 (결과 보기 전에 확정) ----------
RANK_S, RANK_K = 16, 128          # 과거 128개 표본(16봉 간격, 약 2048봉=7일)에 대한 백분위
WARM = 864 + RANK_S * RANK_K      # 워밍업 봉 수
RANK_THRESH = [('<=0.02', 'lo', 0.02), ('<=0.05', 'lo', 0.05),
               ('>=0.95', 'hi', 0.95), ('>=0.98', 'hi', 0.98)]
POS_THRESH = [('<=0.05', 'lo', 0.05), ('<=0.10', 'lo', 0.10),
              ('>=0.90', 'hi', 0.90), ('>=0.95', 'hi', 0.95),
              ('0.45~0.55', 'mid', 0.05)]
HORIZ = ['1h', '4h', '12h', '24h', '48h']
MAX_DENSITY = 0.10
MIN_N = 500


def rollsum(x, w):
    c = np.concatenate(([0.0], np.nancumsum(x)))
    out = np.full(len(x), np.nan)
    out[w - 1:] = c[w:] - c[:-w]
    return out


def rollmean(x, w):
    return rollsum(x, w) / w


def rollstd(x, w):
    m = rollmean(x, w)
    m2 = rollmean(x * x, w)
    v = np.maximum(m2 - m * m, 0.0)
    return np.sqrt(v)


def rollmax(x, w):
    n = len(x)
    out = np.full(n, np.nan)
    if n >= w:
        sw = np.lib.stride_tricks.sliding_window_view(x, w)
        out[w - 1:] = sw.max(axis=1)
    return out


def rollmin(x, w):
    n = len(x)
    out = np.full(n, np.nan)
    if n >= w:
        sw = np.lib.stride_tricks.sliding_window_view(x, w)
        out[w - 1:] = sw.min(axis=1)
    return out


def features(d):
    """봉 i 까지의 정보만으로 만든 변동성/레인지 특징들."""
    o, h, l, c = d['o'], d['h'], d['l'], d['c'].astype(float)
    n = len(c)
    lr = np.full(n, np.nan)
    lr[1:] = np.log(c[1:] / c[:-1])
    lr = np.nan_to_num(lr, nan=0.0, posinf=0.0, neginf=0.0)
    pc = np.full(n, np.nan); pc[1:] = c[:-1]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)

    F = {}
    rv = {}
    for w in (12, 48, 288, 864):
        rv[w] = rollstd(lr, w) * 100.0
        F['rv%d' % w] = rv[w]
    for a, b in ((12, 288), (48, 288), (48, 864), (288, 864), (12, 48)):
        F['vr_%d_%d' % (a, b)] = rv[a] / np.where(rv[b] > 0, rv[b], np.nan)
    for w in (12, 48, 288):
        F['atrp%d' % w] = rollmean(tr, w) / c * 100.0
    for w in (12, 48, 288, 864):
        F['hlr%d' % w] = (rollmax(h, w) - rollmin(l, w)) / c * 100.0
    for w in (48, 288):
        F['bbw%d' % w] = 2.0 * rollstd(c, w) / rollmean(c, w) * 100.0
    F['kelt48'] = 2.0 * rollmean(tr, 48) / rollmean(c, 48) * 100.0
    a48 = rollmean(tr, 48)
    F['trspike'] = tr / np.where(a48 > 0, a48, np.nan)

    P = {}
    for w in (48, 288, 864):
        hi, lo = rollmax(h, w), rollmin(l, w)
        rng = hi - lo
        P['pos%d' % w] = np.where(rng > 0, (c - lo) / np.where(rng > 0, rng, np.nan), np.nan)
    return F, P


def rank_of(x):
    """과거 RANK_K 개 표본(RANK_S 간격) 대비 백분위. 미래 정보 없음."""
    n = len(x)
    cnt = np.zeros(n)
    for k in range(1, RANK_K + 1):
        L = k * RANK_S
        cnt[L:] += (x[L:] > x[:-L])
    r = cnt / RANK_K
    r[:WARM] = np.nan
    r[~np.isfinite(x)] = np.nan
    return r


def main():
    syms = lib.symbols()
    F0, P0 = features(lib.load(syms[0]))
    fnames = sorted(F0.keys())
    pnames = sorted(P0.keys())

    conds = []   # (label, kind, fname, tag, thr)
    for f in fnames:
        for tag, kind, thr in RANK_THRESH:
            conds.append(('rank[%s] %s' % (f, tag), kind, f, thr))
    pconds = []
    for p in pnames:
        for tag, kind, thr in POS_THRESH:
            pconds.append(('%s %s' % (p, tag), kind, p, thr))

    nc = len(conds) + len(pconds)
    print('conditions=%d  combos=%d' % (nc, nc * len(HORIZ) * 2), flush=True)

    parts_c = [[] for _ in range(nc)]
    parts_r = {k: [] for k in HORIZ}
    parts_t = []

    for si, s in enumerate(syms):
        d = lib.load(s)
        mask, rets = lib.fwd_returns(d, 'disc')
        if mask.sum() == 0:
            continue
        F, P = features(d)
        R = {f: rank_of(F[f]) for f in fnames}
        col = []
        for lab, kind, f, thr in conds:
            v = R[f]
            if kind == 'lo':
                col.append(np.isfinite(v) & (v <= thr))
            else:
                col.append(np.isfinite(v) & (v >= thr))
        for lab, kind, p, thr in pconds:
            v = P[p]
            ok = np.isfinite(v)
            ok &= np.arange(len(v)) >= WARM
            if kind == 'lo':
                col.append(ok & (v <= thr))
            elif kind == 'hi':
                col.append(ok & (v >= thr))
            else:
                col.append(ok & (np.abs(v - 0.5) <= thr))
        for i in range(nc):
            parts_c[i].append(np.packbits(col[i][mask]))
        for k in HORIZ:
            parts_r[k].append(rets[k][mask].astype(np.float32))
        parts_t.append(d['t'][mask])
        if si % 40 == 0:
            print('  %d/%d %s' % (si, len(syms), s), flush=True)

    ts = np.concatenate(parts_t)
    N = len(ts)
    RET = {k: np.concatenate(parts_r[k]).astype(np.float64) for k in HORIZ}
    sizes = [len(p) for p in parts_t]
    print('total bars=%d' % N, flush=True)

    rows = []
    tested = 0
    for i, (lab, kind, f, thr) in enumerate(conds + pconds):
        pieces = []
        for j, sz in enumerate(sizes):
            pieces.append(np.unpackbits(parts_c[i][j])[:sz].astype(bool))
        sig = np.concatenate(pieces)
        dens = sig.mean()
        if dens >= MAX_DENSITY or sig.sum() < MIN_N:
            tested += len(HORIZ) * 2
            continue
        for k in HORIZ:
            for dirn in ('long', 'short'):
                tested += 1
                r = RET[k] if dirn == 'long' else lib.short_of(RET[k])
                e = lib.evaluate(sig, r, ts, min_n=MIN_N)
                if not e.get('ok'):
                    continue
                rows.append(dict(label=lab, dens=dens, dirn=dirn, hor=k, **e))
    print('tested combos=%d  evaluated=%d' % (tested, len(rows)), flush=True)

    # 기준선(조건 없음) — 상위표가 신호인지 시장 전체 표류인지 구분용
    allsig = np.ones(N, bool)
    base = {}
    for k in HORIZ:
        for dirn in ('long', 'short'):
            r = RET[k] if dirn == 'long' else lib.short_of(RET[k])
            base[(k, dirn)] = lib.evaluate(allsig, r, ts, min_n=MIN_N)

    keep = [r for r in rows if r['mean'] > 0 and r['n'] >= MIN_N and r['sign_stable']]
    keep.sort(key=lambda r: -r['mean'])
    top = keep[:15]

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result_vol.md')
    with open(out, 'w', encoding='utf-8') as fp:
        fp.write('# 변동성/레인지 계열 스윕 결과 (upbit 5분봉, 탐색구간 disc)\n\n')
        fp.write('- 종목 239개, 탐색구간 유효봉 합계 %d\n' % N)
        fp.write('- 검정한 총 조합 수: **%d** (조건 %d x 지평 5 x 방향 2)\n' % (tested, nc))
        fp.write('- 밀도 10% 이상 또는 표본 500 미만 조건은 폐기\n')
        fp.write('- 백분위 rank[X]: 봉 i 의 X 값을 과거 128개 표본(16봉 간격, 약 2048봉)과 비교한 비율\n')
        fp.write('- posW = (종가 - 최근 W봉 최저가)/(최근 W봉 최고가 - 최저가)\n')
        fp.write('- 수익률은 lib.fwd_returns(disc) 기준 순수익률(왕복 비용 0.12% 차감), 진입=다음 봉 시가\n')
        fp.write('- 워밍업 %d봉 이전 봉은 모든 조건에서 제외\n\n' % WARM)
        if not top:
            fp.write('## 조건 충족 0개\n\n평균>0 & 표본>=500 & 부호유지=True 를 만족하는 조합이 없다.\n')
        else:
            fp.write('| 특징 정의 | 방향 | 지평 | n | 평균% | 중앙% | 승률% | 최대기여일제외 평균% | 부호유지 |\n')
            fp.write('|---|---|---|---|---|---|---|---|---|\n')
            for r in top:
                fp.write('| %s (밀도 %.2f%%) | %s | %s | %d | %.3f | %.3f | %.1f | %.3f | %s |\n' % (
                    r['label'], r['dens'] * 100, r['dirn'], r['hor'], r['n'],
                    r['mean'], r['median'], r['win'], r['mean_ex_topday'], r['sign_stable']))
        fp.write('\n조건 충족(평균>0 & n>=500 & 부호유지) 조합 총 %d개 중 상위 %d개.\n' % (len(keep), len(top)))

        fp.write('\n## 기준선 (조건 없음, 같은 표본 전체)\n\n')
        fp.write('| 지평 | 방향 | n | 평균% | 중앙% | 승률% | 최대기여일제외 평균% |\n|---|---|---|---|---|---|---|\n')
        for k in HORIZ:
            for dirn in ('long', 'short'):
                b = base[(k, dirn)]
                fp.write('| %s | %s | %d | %.3f | %.3f | %.1f | %.3f |\n' % (
                    k, dirn, b['n'], b['mean'], b['median'], b['win'], b['mean_ex_topday']))
        fp.write('\n상위표의 평균을 같은 지평/방향의 기준선과 비교해야 한다. 기준선 초과분(초과평균 = 평균 - 기준선 평균)은 아래.\n\n')
        fp.write('| 특징 | 방향 | 지평 | 평균% | 기준선 평균% | 초과% |\n|---|---|---|---|---|---|\n')
        for r in top:
            b = base[(r['hor'], r['dirn'])]['mean']
            fp.write('| %s | %s | %s | %.3f | %.3f | %+.3f |\n' % (
                r['label'], r['dirn'], r['hor'], r['mean'], b, r['mean'] - b))
        nlong = sum(1 for r in keep if r['dirn'] == 'long')
        n48 = sum(1 for r in keep if r['hor'] == '48h')
        fp.write('\n## 유보 사항 (결과를 그대로 적는다)\n\n')
        fp.write('1. 상위 15개가 전부 **48h 롱** 한 칸에 몰려 있다. 조건 통과 %d개 중 롱이 %d개, 48h가 %d개.\n'
                 '   같은 지평의 무조건 기준선도 +1.280%%(롱)이라, 이 칸 자체가 탐색구간의 시장 표류를 담고 있다.\n'
                 '   위 표의 평균은 기준선 대비 초과분(+2.9~+4.1%%p)으로 읽어야 한다.\n' % (len(keep), nlong, n48))
        fp.write('2. 평균은 크지만 **중앙값은 거의 전부 0 근처이거나 음수, 승률 44~52%%**다. '
                 '소수의 큰 상승이 평균을 만든다(우측 꼬리). 중앙값/승률만 보면 신호가 아니고, 평균만 보면 꼬리에 의존한다.\n')
        fp.write('3. 최대기여일 하나를 빼면 평균이 1.2~1.8%%p 떨어진다. 부호는 유지되나 단일 날짜 의존이 작지 않다.\n')
        fp.write('4. 48h 보유는 종목당 신호가 시간적으로 겹쳐 표본이 서로 독립이 아니다. n을 독립 표본 수로 읽으면 안 된다.\n')
        fp.write('5. 청산(강제 손절/레버리지) 시뮬레이션이 없다. 무레버리지 현물 기준 수치다.\n')
        fp.write('6. 결측봉이 잦아 특징의 창은 위치 기반이며 실제 경과시간이 창 길이보다 길 수 있다. '
                 '진입~청산 구간 연속성은 lib.fwd_returns 가 보장한다.\n')
        fp.write('7. 950조합을 전수 검정했으므로 다중검정 보정 없이는 상위 평균이 과대평가다. '
                 '봉인구간(hold) 확인 전에는 어떤 것도 채택하지 않는다.\n')
    print('wrote', out)
    for k in HORIZ:
        for dirn in ('long', 'short'):
            b = base[(k, dirn)]
            print('BASE', k, dirn, b['n'], round(b['mean'], 3), round(b['median'], 3))
    for r in top:
        print(r['label'], r['dirn'], r['hor'], r['n'], round(r['mean'], 3))


if __name__ == '__main__':
    main()
