"""바이낸스 USDT 무기한선물 5분봉 1년 — 시간대/횡단면/캔들형태 전수 스윕.

절대 규칙:
  - 수익률/비용/펀딩/연속성 계산은 전부 swlib(L) 함수만 사용
  - L.symbols('disc') 만 사용 ('hold' 호출 없음)
  - 과거수익률은 L.fwd_returns 가 만든 LONG[w] 를 시프트해서만 생성

사전확정 격자 (실행 전 확정, 결과 보고 수정 금지):
  진입격자    : 30분 (t % 1800000 == 0) 인 봉만 진입 후보
  지평        : 1h, 4h, 12h, 24h  (L.HORIZONS)
  방향        : LONG, SHORT 둘 다
  횡단면 모수 : 그 시각에 데이터가 있는(해당 과거수익률이 유한한) 종목만.
                모수 종목수 < 30 인 시각은 횡단면 피처를 NaN 처리.
  구간(bin)   : 전체 유한값의 5% 분위 20구간. 검정 대상은
                bin0(0-5%), bin1(5-10%), bin9(45-50%), bin10(50-55%),
                bin18(90-95%), bin19(95-100%) 6개.
  사전 필터   : 밀도 >= 10% 버림 / n < 500 버림 / 종목 < 30 버림 / 날짜 < 30 버림

사용법:
  python bsweep_xsec.py build     # 캐시 생성
  python bsweep_xsec.py sweep     # 전수 검정
  python bsweep_xsec.py report    # 표 생성
"""
import sys, os, json, time, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import swlib as L

D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(D, '_xsec_cache.npz')
RAW = os.path.join(D, '_xsec_raw.pkl')
OUT = os.path.join(D, 'bresult_xsec.md')
RES = os.path.join(D, '_xsec_res.json')

G = 1800000                      # 30분 진입 격자
NT = (L.WIN_E - L.WIN_S) // G + 2    # 30분 슬롯 수
HZ = ['1h', '4h', '12h', '24h']
PW = ['1h', '4h', '12h']         # 과거수익률 창
MIN_XSEC_SYMS = 30
MAX_DENSITY = 0.10
MIN_N = 500
MIN_SYMS = 30
MIN_DAYS = 30


# ---------------------------------------------------------------- build
def build():
    syms = L.symbols('disc')
    print(f'symbols(disc) = {len(syms)}')
    cols = {}
    keys_f32 = [f'{d}_{h}' for d in ('LO', 'SH') for h in HZ] + \
               [f'past_{w}' for w in PW] + ['body', 'upw', 'low', 'cpos', 'rrel']
    for k in keys_f32:
        cols[k] = []
    cols['tidx'] = []
    cols['sid'] = []
    cols['sup'] = []
    cols['sdn'] = []
    t0 = time.time()
    for si, sym in enumerate(syms):
        d = L.load(sym)
        mask, LO, SH = L.fwd_returns(d, sym)
        t = d['t']
        n = len(t)
        sel = mask & (t % G == 0)
        if not sel.any():
            continue
        # 과거수익률: past_w(i) = LONG[w][i-h-1]  (lib이 넣은 NaN 상속)
        past = {}
        for w in PW:
            h = L.HORIZONS[w]
            p = np.full(n, np.nan)
            if n > h + 1:
                p[h + 1:] = LO[w][:n - h - 1]
            past[w] = p
        o, hi, lo, c = d['o'], d['h'], d['l'], d['c']
        rg = hi - lo
        with np.errstate(invalid='ignore', divide='ignore'):
            body = np.where(rg > 0, (c - o) / rg, np.nan)
            upw = np.where(rg > 0, (hi - np.maximum(o, c)) / rg, np.nan)
            loww = np.where(rg > 0, (np.minimum(o, c) - lo) / rg, np.nan)
            cpos = np.where(rg > 0, (c - lo) / rg, np.nan)
        # 최근 288봉(24h) 평균 레인지 대비 현재 레인지
        cs = np.concatenate(([0.0], np.cumsum(np.nan_to_num(rg))))
        avg = np.full(n, np.nan)
        if n > 288:
            avg[288:] = (cs[289:] - cs[1:n - 287]) / 288.0
        with np.errstate(invalid='ignore', divide='ignore'):
            rrel = np.where(avg > 0, rg / avg, np.nan)
        # 연속 양봉/음봉 스트릭
        ii = np.arange(n)
        def streak(b):
            mx = np.maximum.accumulate(np.where(~b, ii, -1))
            return np.minimum(ii - mx, 100).astype(np.int8)
        sup = streak(c > o)
        sdn = streak(c < o)
        for h in HZ:
            cols[f'LO_{h}'].append(LO[h][sel].astype(np.float32))
            cols[f'SH_{h}'].append(SH[h][sel].astype(np.float32))
        for w in PW:
            cols[f'past_{w}'].append(past[w][sel].astype(np.float32))
        for k, v in (('body', body), ('upw', upw), ('low', loww),
                     ('cpos', cpos), ('rrel', rrel)):
            cols[k].append(v[sel].astype(np.float32))
        cols['tidx'].append(((t[sel] - L.WIN_S) // G).astype(np.int32))
        cols['sid'].append(np.full(int(sel.sum()), si, np.int16))
        cols['sup'].append(sup[sel])
        cols['sdn'].append(sdn[sel])
        if si % 100 == 0:
            print(f'  {si}/{len(syms)} {sym} {time.time()-t0:.0f}s', flush=True)
    out = {k: np.concatenate(v) for k, v in cols.items()}
    print('rows', len(out['tidx']), f'{time.time()-t0:.0f}s')
    np.savez(CACHE, **out)
    json.dump(syms, open(os.path.join(D, '_xsec_syms.json'), 'w'))
    print('saved', CACHE)


# ---------------------------------------------------------------- features
def qbins(v, nb=20):
    """전체 유한값 5% 분위 20구간 코드. NaN -> -1"""
    f = np.isfinite(v)
    x = v[f]
    if len(x) > 4_000_000:
        x = x[np.random.default_rng(7).choice(len(x), 4_000_000, replace=False)]
    e = np.quantile(x, np.linspace(0, 1, nb + 1)[1:-1])
    code = np.full(len(v), -1, np.int8)
    code[f] = np.searchsorted(e, v[f], side='right').astype(np.int8)
    return code


def group_rank(v, tidx, cnt_all, start):
    """같은 tidx 안에서의 백분위 순위(0~1). 모수는 그 시각 유한값 종목만."""
    N = len(v)
    fin = np.isfinite(v)
    cnt = np.bincount(tidx[fin], minlength=NT)
    key = np.where(fin, v, np.inf).astype(np.float64)
    ordv = np.lexsort((key, tidx))
    pos = np.arange(N, dtype=np.int64) - start[tidx[ordv]]
    den = (cnt[tidx[ordv]] - 1).astype(np.float64)
    with np.errstate(invalid='ignore', divide='ignore'):
        rp = np.where(den > 0, pos / den, np.nan)
    rk = np.empty(N)
    rk[ordv] = rp
    rk[~fin] = np.nan
    rk[cnt[tidx] < MIN_XSEC_SYMS] = np.nan
    return rk, cnt


def make_features(z, syms):
    N = len(z['tidx'])
    tidx = z['tidx'].astype(np.int64)
    cnt_all = np.bincount(tidx, minlength=NT)
    start = np.concatenate(([0], np.cumsum(cnt_all)))[:-1]
    t = L.WIN_S + tidx.astype(np.int64) * G

    F = {}      # name -> int8 bin code (0..19) 또는 bool
    BOOL = {}

    # ---- 시간
    kst_h = (((t + 9 * 3600000) // 3600000) % 24).astype(np.int8)
    dow = (((t + 9 * 3600000) // 86400000 + 3) % 7).astype(np.int8)   # 0=Mon
    fslot = ((t % (8 * 3600000)) // G).astype(np.int8)                # 0..15, 0=펀딩정산봉
    for k in range(24):
        BOOL[f'KST시각=={k:02d}'] = kst_h == k
    for k, nm in enumerate(['월', '화', '수', '목', '금', '토', '일']):
        BOOL[f'KST요일=={nm}'] = dow == k
    BOOL['주말(토일,KST)'] = dow >= 5
    BOOL['평일(월금,KST)'] = dow < 5
    BOOL['세션=아시아(KST08-16)'] = (kst_h >= 8) & (kst_h < 16)
    BOOL['세션=유럽(KST16-24)'] = kst_h >= 16
    BOOL['세션=미국(KST00-08)'] = kst_h < 8
    for s in range(16):
        BOOL[f'펀딩슬롯=={s:02d}(정산후{s*30}분)'] = fslot == s

    # ---- 횡단면
    XS = {}
    btc_id = syms.index('BTCUSDT') if 'BTCUSDT' in syms else -1
    for w in PW:
        pv = z[f'past_{w}'].astype(np.float64)
        rk, cnt = group_rank(pv, tidx, cnt_all, start)
        fin = np.isfinite(pv)
        s = np.bincount(tidx[fin], weights=pv[fin], minlength=NT)
        with np.errstate(invalid='ignore', divide='ignore'):
            mkt = np.where(cnt >= MIN_XSEC_SYMS, s / np.maximum(cnt, 1), np.nan)
        upc = np.bincount(tidx[fin & (pv > 0)], minlength=NT)
        with np.errstate(invalid='ignore', divide='ignore'):
            brd = np.where(cnt >= MIN_XSEC_SYMS, upc / np.maximum(cnt, 1), np.nan)
        btc = np.full(NT, np.nan)
        if btc_id >= 0:
            bm = (z['sid'] == btc_id) & fin
            btc[tidx[bm]] = pv[bm]
        XS[f'횡단면순위_과거{w}수익'] = rk
        XS[f'시장평균_과거{w}수익'] = mkt[tidx]
        XS[f'시장폭_과거{w}상승비율'] = brd[tidx]
        XS[f'초과수익_과거{w}(개별-시장평균)'] = pv - mkt[tidx]
        XS[f'BTC_과거{w}수익'] = btc[tidx]
        XS[f'BTC대비_과거{w}(개별-BTC)'] = pv - btc[tidx]
        del pv

    # ---- 캔들
    CD = {'캔들몸통비(c-o)/(h-l)': z['body'].astype(np.float64),
          '윗꼬리비(h-max(o,c))/(h-l)': z['upw'].astype(np.float64),
          '아랫꼬리비(min(o,c)-l)/(h-l)': z['low'].astype(np.float64),
          '종가위치(c-l)/(h-l)': z['cpos'].astype(np.float64),
          '레인지비(당봉/24h평균)': z['rrel'].astype(np.float64)}
    BOOL['연속양봉>=4'] = z['sup'] >= 4
    BOOL['연속양봉>=5'] = z['sup'] >= 5
    BOOL['연속음봉>=4'] = z['sdn'] >= 4
    BOOL['연속음봉>=5'] = z['sdn'] >= 5

    codes = {}
    for nm, v in list(XS.items()) + list(CD.items()):
        codes[nm] = qbins(v)
    return BOOL, codes, t


BINS = [(0, '0-5%'), (1, '5-10%'), (9, '45-50%'), (10, '50-55%'),
        (18, '90-95%'), (19, '95-100%')]


# ---------------------------------------------------------------- sweep
def sweep():
    z = dict(np.load(CACHE))
    syms = json.load(open(os.path.join(D, '_xsec_syms.json')))
    N = len(z['tidx'])
    print('rows', N)
    BOOL, codes, t = make_features(z, syms)
    sid = z['sid']

    cands = []          # (name, mask)
    for nm, m in BOOL.items():
        cands.append((nm, m))
    for nm, c in codes.items():
        for b, lab in BINS:
            cands.append((f'{nm} 구간{lab}', c == b))
    # ---- 2요인 조합 (사전확정)
    tails = []
    for nm, c in codes.items():
        if nm.startswith(('횡단면순위', '시장평균', '시장폭', '초과수익', 'BTC')):
            tails.append((f'{nm}[하위5%]', c == 0))
            tails.append((f'{nm}[상위5%]', c == 19))
    partners = [('세션=아시아', BOOL['세션=아시아(KST08-16)']),
                ('세션=유럽', BOOL['세션=유럽(KST16-24)']),
                ('세션=미국', BOOL['세션=미국(KST00-08)']),
                ('주말', BOOL['주말(토일,KST)']),
                ('펀딩정산봉', BOOL['펀딩슬롯==00(정산후0분)']),
                ('펀딩정산30분전', BOOL['펀딩슬롯==15(정산후450분)']),
                ('연속양봉>=4', BOOL['연속양봉>=4']),
                ('연속음봉>=4', BOOL['연속음봉>=4']),
                ('몸통비하위5%', codes['캔들몸통비(c-o)/(h-l)'] == 0),
                ('몸통비상위5%', codes['캔들몸통비(c-o)/(h-l)'] == 19),
                ('종가위치하위5%', codes['종가위치(c-l)/(h-l)'] == 0),
                ('종가위치상위5%', codes['종가위치(c-l)/(h-l)'] == 19),
                ('레인지비상위5%', codes['레인지비(당봉/24h평균)'] == 19)]
    for tn, tm in tails:
        for pn, pm in partners:
            cands.append((f'{tn} & {pn}', tm & pm))
    # 시장 vs 개별 엇갈림 조합
    for w in PW:
        rk = codes[f'횡단면순위_과거{w}수익']
        mk = codes[f'시장평균_과거{w}수익']
        bd = codes[f'시장폭_과거{w}상승비율']
        ex = codes[f'초과수익_과거{w}(개별-시장평균)']
        cands.append((f'시장평균{w}상위5% & 횡단면순위{w}하위5%(시장오를때 안오른종목)', (mk == 19) & (rk == 0)))
        cands.append((f'시장평균{w}하위5% & 횡단면순위{w}상위5%(시장내릴때 안내린종목)', (mk == 0) & (rk == 19)))
        cands.append((f'시장폭{w}상위5% & 횡단면순위{w}하위5%', (bd == 19) & (rk == 0)))
        cands.append((f'시장폭{w}하위5% & 횡단면순위{w}상위5%', (bd == 0) & (rk == 19)))
        cands.append((f'시장평균{w}상위5% & 초과수익{w}하위5%', (mk == 19) & (ex == 0)))
        cands.append((f'시장평균{w}하위5% & 초과수익{w}상위5%', (mk == 0) & (ex == 19)))
        cands.append((f'시장평균{w}상위5% & 초과수익{w}상위5%', (mk == 19) & (ex == 19)))
        cands.append((f'시장평균{w}하위5% & 초과수익{w}하위5%', (mk == 0) & (ex == 0)))

    print('candidate features:', len(cands))
    total_tests = 0
    dropped_density = 0
    rows = []
    t0 = time.time()
    oct_m = (t >= 1759276800000) & (t < 1761955200000)   # 2025-10-01 ~ 2025-11-01 UTC
    for ci, (nm, m) in enumerate(cands):
        dens = float(m.mean())
        total_tests += len(HZ) * 2
        if dens >= MAX_DENSITY:
            dropped_density += len(HZ) * 2
            continue
        if m.sum() < MIN_N:
            continue
        for h in HZ:
            for dr, key in (('LONG', f'LO_{h}'), ('SHORT', f'SH_{h}')):
                r = z[key]
                res = L.evaluate(m, r, t, min_n=MIN_N, sym_ids=sid)
                if not res.get('ok'):
                    continue
                res.update(feat=nm, dir=dr, hz=h, density=dens)
                mo = m & oct_m
                if mo.sum() >= 1:
                    o = L.evaluate(mo, r, t, min_n=1, sym_ids=sid)
                    res['oct_n'] = o.get('n', 0)
                    res['oct_mean'] = o.get('mean')
                else:
                    res['oct_n'] = 0; res['oct_mean'] = None
                rows.append(res)
        if ci % 25 == 0:
            print(f'  {ci}/{len(cands)} kept={len(rows)} {time.time()-t0:.0f}s', flush=True)

    # ---- 무조건 진입 기준선
    base = []
    allm = np.ones(N, bool)
    for h in HZ:
        for dr, key in (('LONG', f'LO_{h}'), ('SHORT', f'SH_{h}')):
            res = L.evaluate(allm, z[key], t, min_n=MIN_N, sym_ids=sid)
            res.update(feat='무조건 진입(전 봉)', dir=dr, hz=h, density=1.0)
            mo = allm & oct_m
            o = L.evaluate(mo, z[key], t, min_n=1, sym_ids=sid)
            res['oct_n'] = o.get('n', 0); res['oct_mean'] = o.get('mean')
            base.append(res)
            print('base', dr, h, res['mean'], flush=True)
    json.dump({'rows': rows, 'base': base, 'total_tests': total_tests,
               'n_features': len(cands), 'dropped_density': dropped_density,
               'N': N}, open(RES, 'w'))
    print('done', len(rows), 'evals kept;', total_tests, 'total tests')


# ---------------------------------------------------------------- report
def report():
    d = json.load(open(RES))
    rows = d['rows']
    good = [r for r in rows if r['mean'] > 0 and r['n'] >= MIN_N
            and r.get('nsyms', 0) >= MIN_SYMS and r['ndays'] >= MIN_DAYS
            and r['sign_stable']]
    good.sort(key=lambda r: -r['mean'])
    top = good[:15]
    hdr = ('| 특징 정의(정확히) | 방향 | 지평 | n | 종목수 | 날짜수 | 평균% | 중앙% | '
           '승률% | 최대기여일제외 | 월 부호일치/총월 |\n|---|---|---|---|---|---|---|---|---|---|---|\n')

    def row(r, star=True):
        m = f"**{r['months_same_sign']}/{r['months_total']}**" if (
            star and r['months_same_sign'] >= 8) else f"{r['months_same_sign']}/{r['months_total']}"
        return (f"| {r['feat']} | {r['dir']} | {r['hz']} | {r['n']} | {r.get('nsyms')} | "
                f"{r['ndays']} | {r['mean']:.4f} | {r['median']:.4f} | {r['win']:.1f} | "
                f"{r['mean_ex_topday']:.4f} | {m} |\n")

    s = ['# 바이낸스 5분봉 1년 — 시간대/횡단면/캔들형태 전수 스윕 결과\n\n']
    s.append(f"- 종목: `swlib.symbols('disc')` {610}종목 (holdout 미사용)\n")
    s.append(f"- 진입격자: 30분(t%1800000==0), 창 2025-08-01~2026-08-01, 총 후보행 {d['N']:,}\n")
    s.append(f"- **검정한 총 조합 수: {d['total_tests']:,}** "
             f"(특징 {d['n_features']:,}개 × 지평4 × 방향2; 밀도≥10%로 사전탈락 {d['dropped_density']:,})\n")
    s.append('- 사전필터: 밀도<10%, n>=500, 종목>=30, 날짜>=30, 부호유지=True\n')
    s.append('- 횡단면 집계 모수: **그 시각에 해당 과거수익률이 유한한 종목만**. '
             '모수<30종목인 시각은 NaN 처리해 제외.\n\n')
    s.append('## 무조건 진입 기준선\n\n' + hdr)
    for r in d['base']:
        s.append(row(r, star=False))
    s.append('\n## 조건 충족 상위 15\n\n')
    if not top:
        s.append('**조건 충족 0개**\n')
    else:
        s.append(hdr)
        for r in top:
            s.append(row(r))
        s.append(f"\n- 조건 충족 총 {len(good)}개 중 평균 내림차순 상위 15개.\n")
        s.append('- **굵게 표시 = 월 부호일치 8/12 이상 (핵심 기준)**\n')
        s.append('\n## 상위 후보의 2025-10 한 달 성적\n\n')
        s.append('| 특징 | 방향 | 지평 | 2025-10 n | 2025-10 평균% | 전체 평균% |\n|---|---|---|---|---|---|\n')
        for r in top:
            om = f"{r['oct_mean']:.4f}" if r['oct_mean'] is not None else '-'
            s.append(f"| {r['feat']} | {r['dir']} | {r['hz']} | {r['oct_n']} | {om} | {r['mean']:.4f} |\n")
        s.append('\n### 기준선의 2025-10\n\n| 방향 | 지평 | n | 평균% |\n|---|---|---|---|\n')
        for r in d['base']:
            om = f"{r['oct_mean']:.4f}" if r['oct_mean'] is not None else '-'
            s.append(f"| {r['dir']} | {r['hz']} | {r['oct_n']} | {om} |\n")

        g8 = sorted([r for r in good if r['months_same_sign'] >= 8], key=lambda r: -r['mean'])
        s.append(f'\n## 참고 1 — 월 부호일치 8/12 이상만 (핵심 기준 통과, 총 {len(g8)}개) 상위 15\n\n' + hdr)
        for r in g8[:15]:
            s.append(row(r))
        sg = sorted([r for r in good if ' & ' not in r['feat']], key=lambda r: -r['mean'])
        s.append(f'\n## 참고 2 — 단일요인(조합 아님)만, 통과 {len(sg)}개 중 상위 15\n\n' + hdr)
        for r in sg[:15]:
            s.append(row(r))
        wd = sorted([r for r in good if r['ndays'] >= 200], key=lambda r: -r['mean'])
        s.append(f'\n## 참고 3 — 날짜 200일 이상 분산된 것만 (시간 집중 위험 낮음), 통과 {len(wd)}개 중 상위 15\n\n' + hdr)
        for r in wd[:15]:
            s.append(row(r))
        s.append('\n## 주의사항 (해석 시 반드시 같이 읽을 것)\n\n')
        s.append(f"1. **다중검정 미보정.** 총 {d['total_tests']:,}검정 중 {len(good)}개가 사전필터를 통과했다"
                 f" (통과율 {len(good)/max(d['total_tests'],1)*100:.1f}%). p값 보정을 하지 않았으므로 "
                 '상위 표는 후보 목록이지 검증된 신호가 아니다.\n')
        s.append('2. **날짜 집중.** 상위 후보 다수가 날짜수 40~130일이다. 시장 전체 지표(시장폭/시장평균/BTC)의 '
                 '5% 꼬리는 특정 시기에 뭉쳐서 발생하므로, n이 커도 실질 독립 관측은 훨씬 적다. '
                 '참고 3의 날짜 200일 이상 목록이 이 위험이 가장 낮다.\n')
        s.append('3. **표본 중복.** 30분 격자 진입 × 24h 보유이므로 같은 종목의 인접 표본이 47봉까지 겹친다. '
                 'n은 독립 표본 수가 아니다.\n')
        s.append('4. **구간 경계에 미래 정보.** 5% 분위 경계는 1년 전체 분포로 산출했다(정규화 수준의 lookahead). '
                 '실거래 규칙으로 옮기려면 확장창 분위로 다시 계산해야 한다.\n')
        s.append('5. **단위.** 모든 평균/중앙/기준선 수치는 `swlib.fwd_returns` 정의대로 '
                 '**명목가 기준 순수익률 %**(왕복 비용 0.12%p + 실측 펀딩 반영)다. 증거금 기준이 아니다.\n')
        s.append('6. **청산 시뮬레이션 없음.** 보유 중 강제청산/스탑을 모형화하지 않은 만기청산 수익률이다.\n')
    open(OUT, 'w', encoding='utf-8').write(''.join(s))
    print(''.join(s))


if __name__ == '__main__':
    {'build': build, 'sweep': sweep, 'report': report}[sys.argv[1]]()
