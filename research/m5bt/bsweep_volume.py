"""거래대금(qv) 계열 전수 스윕 — 바이낸스 USDT 무기한선물 5분봉 1년.

절대 규칙:
  - 수익률/비용/펀딩/연속성 계산은 전부 swlib(L)에게 맡긴다. 직접 계산 금지.
  - symbols('disc')만 사용. 'hold'는 절대 호출하지 않는다.

데이터 컬럼: t, o, h, l, c, qv  (qv = quote volume = 거래대금 USDT)
  * base volume(코인 수량), 체결건수(trade count) 컬럼 없음
    -> "봉당 평균 체결액"은 계산 불가.

실행 구조 (5천만 봉 대응):
  0) 밀도 패스  : 특징별 발생밀도만 집계 -> 밀도>=10% 특징 폐기
  1) 수집 패스  : 종목 100개 배치, 살아남은 특징의 합집합 행만 배치파일로 디스크 저장(재개 가능)
  2) 병합       : 배치파일 -> memmap .npy
  3) 평가       : 특징별 np.flatnonzero 인덱스만 뽑아 swlib.evaluate 1회 호출
격자는 build_features()에 실행 전 고정한다(사후 미세조정 금지).
"""
import sys, os, time, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import swlib as L

D = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(D, '_bvol_parts')
OUT_MD = os.path.join(D, 'bresult_volume.md')
OUT_JSON = os.path.join(D, 'bsweep_volume_raw.json')
DENS_F = os.path.join(WORK, 'density.json')
BASE_F = os.path.join(WORK, 'baseline.json')

MIN_N, MIN_SYMS, MIN_DAYS = 500, 30, 30
MAX_DENSITY = 0.10                              # 밀도 10% 이상이면 폐기(사전등록)
OCT_S, OCT_E = 1759276800000, 1761955200000     # 2025-10-01 ~ 2025-11-01 UTC
BATCH = 100
BASE_STEP = 20                                  # 기준선 계통추출 간격

HORIZONS = ['1h', '4h', '12h', '24h', '48h']
SIDES = ['L', 'S']
KEYS = [f'{s}_{h}' for s in SIDES for h in HORIZONS]     # 10개 수익률 계열


# ---------------------------------------------------------------------------
# 격자(고정) — 최초 계획 78개에서 절반인 39개로 축소
# ---------------------------------------------------------------------------
MED_N = [48, 288, 864]          # (축소: 12 제외)
SURGE_T = [3, 5, 10, 20]
DIR_N = 288                     # (축소: 봉방향 조합은 med288 에서만)
LEVEL_EDGES = [(None, 4), (4, 5), (5, 6), (6, 7), (7, None)]
TREND_UP_T = [2.0, 3.0, 5.0]
TREND_DN_T = [0.5, 0.3]         # (축소: 0.2 제외)
QUIET_X = [5.0, 10.0]           # (축소: 3% 제외)
CONC_N = 288                    # (축소: 48 제외)
CONC_T = [0.3, 0.5, 0.7]


def build_features(d):
    """반환 (names, bool 2D (n_bars, n_feat)) — 순서 고정. 전부 과거정보만 사용."""
    qv = d['qv'].astype(np.float64)
    o, c = d['o'], d['c']
    n = len(qv)
    s = pd.Series(qv)

    med = {N: s.rolling(N, min_periods=N).median().to_numpy() for N in MED_N}
    mean288 = s.rolling(288, min_periods=288).mean().to_numpy()
    mean12 = s.rolling(12, min_periods=12).mean().to_numpy()
    ratio = {N: np.divide(qv, med[N], out=np.full(n, np.nan),
                          where=np.isfinite(med[N]) & (med[N] > 0)) for N in MED_N}
    trend = np.divide(mean12, mean288, out=np.full(n, np.nan),
                      where=np.isfinite(mean288) & (mean288 > 0))
    mx = s.rolling(CONC_N, min_periods=CONC_N).max().to_numpy()
    sm = s.rolling(CONC_N, min_periods=CONC_N).sum().to_numpy()
    conc = np.divide(mx, sm, out=np.full(n, np.nan),
                     where=np.isfinite(sm) & (sm > 0))
    with np.errstate(divide='ignore', invalid='ignore'):
        lq = np.log10(np.where(mean288 > 0, mean288, np.nan))
    up, dn = c > o, c < o
    r12 = np.full(n, np.nan)
    r12[12:] = (c[12:] / c[:-12] - 1.0) * 100.0     # 최근 12봉 가격변화 %(과거)

    names, feats = [], []
    def add(nm, arr):
        names.append(nm); feats.append(np.asarray(arr, bool))

    # A. 급증배수 12개
    for N in MED_N:
        for T in SURGE_T:
            add(f'qv/med{N} >= {T}', ratio[N] >= T)
    # B. 급증 x 봉방향 8개
    for T in SURGE_T:
        b = ratio[DIR_N] >= T
        add(f'qv/med{DIR_N} >= {T} & 양봉', b & up)
        add(f'qv/med{DIR_N} >= {T} & 음봉', b & dn)
    # C. 거래대금 절대 수준 5개
    for lo, hi in LEVEL_EDGES:
        if lo is None:
            add(f'log10(mean288 qv) < {hi}', lq < hi)
        elif hi is None:
            add(f'log10(mean288 qv) >= {lo}', lq >= lo)
        else:
            add(f'{lo} <= log10(mean288 qv) < {hi}', (lq >= lo) & (lq < hi))
    # D. 거래량 추세 5개
    for T in TREND_UP_T:
        add(f'mean12/mean288 >= {T}', trend >= T)
    for T in TREND_DN_T:
        add(f'mean12/mean288 <= {T}', trend <= T)
    # E. 조용한데 가격만 움직임 4개
    quiet = ratio[288] <= 1.2
    for X in QUIET_X:
        add(f'qv/med288 <= 1.2 & 12봉가격 >= +{X}%', quiet & (r12 >= X))
        add(f'qv/med288 <= 1.2 & 12봉가격 <= -{X}%', quiet & (r12 <= -X))
    # F. 거래대금 집중도 3개
    for T in CONC_T:
        add(f'max/sum(qv,{CONC_N}) >= {T}', conc >= T)
    # G. 급증 x 유동성 2개
    b5 = ratio[288] >= 5
    add('qv/med288 >= 5 & log10(mean288 qv) >= 6', b5 & (lq >= 6))
    add('qv/med288 >= 5 & log10(mean288 qv) < 6', b5 & (lq < 6))

    return names, np.column_stack(feats)


def feature_names():
    return build_features({'qv': np.ones(2000), 'o': np.ones(2000),
                           'c': np.ones(2000)})[0]


# ---------------------------------------------------------------------------
def pass_density(syms):
    if os.path.exists(DENS_F):
        j = json.load(open(DENS_F, encoding='utf-8'))
        print('density: 캐시 사용', flush=True)
        return j['names'], np.array(j['dens']), j['totbars']
    names, hits, tot = None, None, 0
    for i, sym in enumerate(syms):
        d = L.load(sym)
        m, _, _ = L.fwd_returns(d, sym)
        nm, F = build_features(d)
        if names is None:
            names = nm; hits = np.zeros(len(nm), np.int64)
        hits += (F & m[:, None]).sum(axis=0)
        tot += int(m.sum())
        if (i + 1) % 100 == 0:
            print(f'  density {i+1}/{len(syms)}', flush=True)
    dens = hits / max(tot, 1)
    json.dump({'names': names, 'dens': dens.tolist(), 'totbars': tot},
              open(DENS_F, 'w', encoding='utf-8'), ensure_ascii=False)
    return names, dens, tot


def pass_collect(syms, keep_idx):
    """종목 100개 배치. 배치별 파일이 있으면 건너뛴다(재개 가능)."""
    nb = (len(syms) + BATCH - 1) // BATCH
    for b in range(nb):
        f = os.path.join(WORK, f'batch_{b:02d}.npz')
        if os.path.exists(f):
            print(f'  batch {b+1}/{nb} 건너뜀(이미 있음)', flush=True)
            continue
        chunk = syms[b * BATCH:(b + 1) * BATCH]
        acc = {k: [] for k in KEYS}
        bacc = {k: [] for k in KEYS}
        ts, sids, packs, bts, bsids = [], [], [], [], []
        t0 = time.time()
        for j, sym in enumerate(chunk):
            gi = b * BATCH + j                     # 전역 종목 인덱스
            d = L.load(sym)
            m, LO, SH = L.fwd_returns(d, sym)
            R = {f'L_{h}': LO[h] for h in HORIZONS}
            R.update({f'S_{h}': SH[h] for h in HORIZONS})
            _, F = build_features(d)
            F = F[:, keep_idx]
            idx = np.flatnonzero(m & F.any(axis=1))     # True 인덱스만 보관
            if len(idx):
                for k in KEYS:
                    acc[k].append(R[k][idx].astype(np.float32))
                ts.append(d['t'][idx])
                sids.append(np.full(len(idx), gi, np.int16))
                packs.append(np.packbits(F[idx], axis=1))
            bidx = np.flatnonzero(m)[::BASE_STEP]       # 기준선용 계통추출
            if len(bidx):
                for k in KEYS:
                    bacc[k].append(R[k][bidx].astype(np.float32))
                bts.append(d['t'][bidx])
                bsids.append(np.full(len(bidx), gi, np.int16))
        out = {k: np.concatenate(acc[k]) for k in KEYS}
        for k in KEYS:
            acc[k] = None
        out['t'] = np.concatenate(ts); out['sid'] = np.concatenate(sids)
        out['pack'] = np.concatenate(packs)
        for k in KEYS:
            out['b_' + k] = np.concatenate(bacc[k]); bacc[k] = None
        out['b_t'] = np.concatenate(bts); out['b_sid'] = np.concatenate(bsids)
        np.savez(f + '.tmp.npz', **out)
        os.replace(f + '.tmp.npz', f)
        print(f'  batch {b+1}/{nb} rows={len(out["t"]):,} '
              f'base={len(out["b_t"]):,} {time.time()-t0:.0f}s', flush=True)
        del out
    return nb


def merge(nb):
    """배치파일 -> memmap .npy. 반환 (mm dict, t, sid, pack, base dict)."""
    files = [os.path.join(WORK, f'batch_{b:02d}.npz') for b in range(nb)]
    sizes, bsizes, nbytes = [], [], None
    for f in files:
        with np.load(f) as z:
            sizes.append(z['t'].shape[0]); bsizes.append(z['b_t'].shape[0])
            nbytes = z['pack'].shape[1]
    N, BN = sum(sizes), sum(bsizes)
    print(f'merge: 총 {N:,} 행 (기준선 {BN:,} 행), pack {nbytes}B/행', flush=True)

    def mm(name, shape, dtype):
        p = os.path.join(WORK, name + '.npy')
        return np.lib.format.open_memmap(p, mode='w+', dtype=dtype, shape=shape)

    M = {k: mm(k, (N,), np.float32) for k in KEYS}
    T = mm('t', (N,), np.int64); S = mm('sid', (N,), np.int16)
    P = mm('pack', (N, nbytes), np.uint8)
    B = {k: [] for k in KEYS}; BT, BS = [], []
    off = 0
    for i, f in enumerate(files):
        with np.load(f) as z:
            n = sizes[i]
            for k in KEYS:
                M[k][off:off + n] = z[k]
            T[off:off + n] = z['t']; S[off:off + n] = z['sid']
            P[off:off + n] = z['pack']
            for k in KEYS:
                B[k].append(z['b_' + k])
            BT.append(z['b_t']); BS.append(z['b_sid'])
        off += n
        print(f'  merged {i+1}/{len(files)}', flush=True)
    for k in KEYS:
        M[k].flush()
    T.flush(); S.flush(); P.flush()
    base = {k: np.concatenate(B[k]).astype(np.float64) for k in KEYS}
    base['t'] = np.concatenate(BT); base['sid'] = np.concatenate(BS)
    return M, T, S, P, base


# ---------------------------------------------------------------------------
def main():
    os.makedirs(WORK, exist_ok=True)
    t0 = time.time()
    syms = L.symbols('disc')
    names_all = feature_names()
    print(f'symbols(disc)={len(syms)}  features={len(names_all)} (계획 78개에서 절반 축소)',
          flush=True)

    names, dens, totbars = pass_density(syms)
    print(f'density done. in-window bars={totbars:,} ({time.time()-t0:.0f}s)', flush=True)
    keep_idx = np.where(dens < MAX_DENSITY)[0]
    dropped = [(names[i], float(dens[i])) for i in range(len(names))
               if dens[i] >= MAX_DENSITY]
    print(f'밀도<10% 통과 {len(keep_idx)}/{len(names)}', flush=True)

    nb = pass_collect(syms, keep_idx)
    print(f'collect done ({time.time()-t0:.0f}s)', flush=True)

    M, T, S, P, base = merge(nb)
    print(f'merge done ({time.time()-t0:.0f}s)', flush=True)

    # 기준선 — 무조건 진입
    bres = {}
    ones = np.ones(len(base['t']), bool)
    for k in KEYS:
        bres[k] = L.evaluate(ones, base[k], base['t'], min_n=MIN_N,
                             sym_ids=base['sid'])
    json.dump(bres, open(BASE_F, 'w', encoding='utf-8'), ensure_ascii=False, default=str)
    del base
    print(f'baseline done ({time.time()-t0:.0f}s)', flush=True)

    Tv = np.asarray(T); Sv = np.asarray(S)
    results, n_tested = [], 0
    for j, gi in enumerate(keep_idx):
        byte = np.asarray(P[:, j // 8])
        idx = np.flatnonzero((byte >> (7 - (j % 8))) & 1)   # 신호 True 인덱스만
        t_s = Tv[idx]; s_s = Sv[idx]
        oct_s = (t_s >= OCT_S) & (t_s < OCT_E)
        ones_s = np.ones(len(idx), bool)
        for k in KEYS:
            r = np.asarray(M[k][idx], np.float64)
            res = L.evaluate(ones_s, r, t_s, min_n=MIN_N, sym_ids=s_s)
            n_tested += 1
            if not res.get('ok'):
                continue
            res.update(name=names[gi], side='LONG' if k[0] == 'L' else 'SHORT',
                       h=k[2:], density=float(dens[gi]))
            res['oct'] = L.evaluate(oct_s, r, t_s, min_n=1, sym_ids=s_s)
            results.append(res)
        print(f'  eval {j+1}/{len(keep_idx)} n={len(idx):,} ({time.time()-t0:.0f}s)',
              flush=True)

    print(f'tested combos = {n_tested} ({time.time()-t0:.0f}s)', flush=True)
    json.dump({'results': results, 'baseline': bres, 'dropped_density': dropped,
               'n_features': len(names), 'n_kept': int(len(keep_idx)),
               'n_tested': n_tested, 'totbars': totbars},
              open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, default=str)
    write_report(results, bres, dropped, len(names), len(keep_idx), n_tested,
                 totbars, len(syms))
    print(f'DONE {time.time()-t0:.0f}s -> {OUT_MD}', flush=True)


def write_report(results, base, dropped, nfeat, nkept, n_tested, totbars, nsym):
    passed = [r for r in results
              if r['mean'] > 0 and r['n'] >= MIN_N and r.get('nsyms', 0) >= MIN_SYMS
              and r['ndays'] >= MIN_DAYS and r['sign_stable']]
    passed.sort(key=lambda r: -r['mean'])
    top = passed[:15]
    li = []; A = li.append

    A('# 거래대금(qv) 계열 전수 스윕 결과')
    A('')
    A(f'- 데이터: 바이낸스 USDT 무기한선물 5분봉, `swlib.symbols(\'disc\')` {nsym}종목, '
      f'창 2025-08-01~2026-08-01, in-window 봉 {totbars:,}')
    A('- 사용 가능 컬럼: `t, o, h, l, c, qv` — **거래대금 = `qv`(quote volume, USDT)**. '
      'base volume(코인 수량)·체결건수 컬럼은 없음 → 봉당 평균체결액은 계산 불가.')
    A(f'- 특징 격자 **{nfeat}개**(최초 계획 78개에서 절반으로 축소 — 5천만 봉 완주 우선) '
      f'→ 밀도<10% 통과 {nkept}개')
    A(f'- **검정한 총 조합 수 = {n_tested}** (통과 특징 {nkept} x 지평 5 x 방향 2)')
    A(f'- 사전등록 필터: 밀도<10%, n>={MIN_N}, 종목>={MIN_SYMS}, 날짜>={MIN_DAYS}, '
      '부호유지=True, 평균>0')
    A('- 수익률은 전부 `swlib.fwd_returns` — **명목가 기준** 순수익률 %'
      '(왕복 비용 0.12% + 실측 펀딩 반영). 진입=다음봉 시가, 청산=h봉 뒤 종가.')
    A('')
    A(f'## 무조건 진입 기준선 (전 봉 1/{BASE_STEP} 계통추출)')
    A('')
    A('| 방향 | 지평 | n | 평균%(명목) | 중앙%(명목) | 승률% |')
    A('|---|---|---|---|---|---|')
    for s, lab in (('L', 'LONG'), ('S', 'SHORT')):
        for h in HORIZONS:
            b = base[f'{s}_{h}']
            A(f"| {lab} | {h} | {b['n']:,} | {b['mean']:+.4f} | {b['median']:+.4f} "
              f"| {b['win']:.2f} |")
    A('')
    A('## 조건 충족 상위 15개 (평균 내림차순)')
    A('')
    if not top:
        A('**조건 충족 0개.**')
    else:
        A('| 특징 정의(정확히) | 방향 | 지평 | n | 종목수 | 날짜수 | 평균%(명목) | '
          '중앙%(명목) | 승률% | 최대기여일제외 | 월 부호일치/총월 | 8/12 이상 |')
        A('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for r in top:
            ok8 = 'O' if r['months_same_sign'] >= 8 else ''
            A(f"| `{r['name']}` | {r['side']} | {r['h']} | {r['n']:,} | {r['nsyms']} | "
              f"{r['ndays']} | {r['mean']:+.4f} | {r['median']:+.4f} | {r['win']:.2f} | "
              f"{r['mean_ex_topday']:+.4f} | {r['months_same_sign']}/{r['months_total']} "
              f"| {ok8} |")
    A('')
    A('## 상위 후보의 2025-10 한 달 성적 (알트 대폭등 구간)')
    A('')
    A('| 특징 | 방향 | 지평 | 2025-10 n | 평균%(명목) | 중앙%(명목) | 승률% |')
    A('|---|---|---|---|---|---|---|')
    for r in top:
        o = r['oct']
        if o.get('ok'):
            A(f"| `{r['name']}` | {r['side']} | {r['h']} | {o['n']:,} | {o['mean']:+.4f} "
              f"| {o['median']:+.4f} | {o['win']:.2f} |")
        else:
            A(f"| `{r['name']}` | {r['side']} | {r['h']} | {o.get('n', 0)} | - | - | - |")
    A('')
    A('## 밀도 10% 이상으로 폐기된 특징')
    A('')
    if dropped:
        A('| 특징 | 밀도 |'); A('|---|---|')
        for nm, dv in dropped:
            A(f'| `{nm}` | {dv*100:.1f}% |')
    else:
        A('없음')
    A('')
    open(OUT_MD, 'w', encoding='utf-8').write('\n'.join(li))


if __name__ == '__main__':
    main()
