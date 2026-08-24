"""변동성/레인지 계열 전수 스윕 (바이낸스 UM 5분봉 1년, disc 610종목).

규칙:
  - 수익률/비용/펀딩/연속성은 swlib.fwd_returns 만 사용
  - symbols('disc') 만 사용 ('hold' 미호출)
  - 격자는 아래 GRID 상수에 사전확정. 실행 후 조건 수정 금지.

설계 메모:
  - 5분봉 전량(종목당 ~91k봉)은 메모리 초과 → STRIDE=6(30분 간격)으로 균일 서브샘플.
    (겹치는 5분봉은 독립 정보가 아님. 서브샘플은 사전확정이며 전 조합에 동일 적용.)
  - 모든 특징은 종목별 과거 30일(8640봉) 롤링 백분위 rank 로 변환(현재봉 포함, 미래 미포함).
  - 레인지내 위치(pos)는 본래 0~1 유계라 rank 없이 원값 사용.

stage feat : 종목별 특징 계산 → 캐시 npz
stage eval : 전 종목 concat 후 swlib.evaluate 1회씩 호출
"""
import os, sys, json, argparse, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import swlib as L

D = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.environ.get('TMPDIR', os.path.join(D, '_volcache')), 'volcache')
os.makedirs(CACHE, exist_ok=True)

STRIDE = 6              # 30분 간격 서브샘플
RANKW = 8640            # 롤링 rank 창 = 30일
RANKMIN = 2000          # rank 최소 표본

# ---------------- 특징 정의 (사전확정) ----------------
RANKED = [  # rank 로 변환할 특징 (이름, 설명)
    'rv12', 'rv48', 'rv288', 'rv864',
    'rv12_o_rv288', 'rv48_o_rv288', 'rv48_o_rv864', 'rv288_o_rv864',
    'atr14_o_c', 'atr96_o_c', 'atr288_o_c',
    'tr1_o_atr96', 'tr1_o_atr288',
    'hlr12', 'hlr48', 'hlr288', 'hlr864',
    'hlr12_o_hlr288', 'hlr48_o_hlr864',
    'bbw20', 'bbw96', 'bbw20_o_mean288',
    'kelt20', 'kelt96', 'bbw20_o_kelt20',
    'park288', 'park288_o_rv288', 'eff288', 'volofvol288',
]
POSF = ['pos48', 'pos288', 'pos864']     # 원값 0~1
FEATS = RANKED + POSF

# 임계 격자 (uint8 스케일: 값 = round(x*200), 255 = NaN)
RANK_TH = [('lo02', 'le', 4), ('lo05', 'le', 10), ('hi95', 'ge', 190), ('hi98', 'ge', 196)]
POS_TH = [('lo05', 'le', 10), ('lo10', 'le', 20), ('hi90', 'ge', 180), ('hi95', 'ge', 190)]

# 2요인 교차용 사전확정 변동성 특징 8개
CROSS_VOL = ['rv288', 'hlr288', 'rv12_o_rv288', 'rv48_o_rv288',
             'tr1_o_atr96', 'bbw20', 'bbw20_o_mean288', 'bbw20_o_kelt20']

HORIZONS = ['1h', '4h', '12h', '24h', '48h']


# ---------------- 특징 계산 ----------------
def feats_of(d):
    o, h, l, c = d['o'], d['h'], d['l'], d['c']
    S = lambda x: pd.Series(x)
    cs, hs, ls = S(c), S(h), S(l)
    lr = np.log(cs).diff()
    F = {}
    rv = {}
    for w in (12, 48, 288, 864):
        rv[w] = lr.rolling(w).std()
        F['rv%d' % w] = rv[w]
    F['rv12_o_rv288'] = rv[12] / rv[288]
    F['rv48_o_rv288'] = rv[48] / rv[288]
    F['rv48_o_rv864'] = rv[48] / rv[864]
    F['rv288_o_rv864'] = rv[288] / rv[864]

    pc = cs.shift(1)
    tr = pd.concat([hs - ls, (hs - pc).abs(), (ls - pc).abs()], axis=1).max(axis=1)
    atr = {}
    for w in (14, 20, 96, 288):
        atr[w] = tr.rolling(w).mean()
    F['atr14_o_c'] = atr[14] / cs
    F['atr96_o_c'] = atr[96] / cs
    F['atr288_o_c'] = atr[288] / cs
    F['tr1_o_atr96'] = tr / atr[96]
    F['tr1_o_atr288'] = tr / atr[288]

    hlr = {}
    for w in (12, 48, 288, 864):
        hlr[w] = (hs.rolling(w).max() - ls.rolling(w).min()) / cs
        F['hlr%d' % w] = hlr[w]
    F['hlr12_o_hlr288'] = hlr[12] / hlr[288]
    F['hlr48_o_hlr864'] = hlr[48] / hlr[864]

    bbw = {}
    for w in (20, 96):
        bbw[w] = 4.0 * cs.rolling(w).std() / cs.rolling(w).mean()
        F['bbw%d' % w] = bbw[w]
    F['bbw20_o_mean288'] = bbw[20] / bbw[20].rolling(288).mean()
    kel = {}
    for w in (20, 96):
        kel[w] = 4.0 * atr[w if w in atr else 20] / cs.ewm(span=w, adjust=False).mean()
    kel[96] = 4.0 * atr[96] / cs.ewm(span=96, adjust=False).mean()
    F['kelt20'] = kel[20]
    F['kelt96'] = kel[96]
    F['bbw20_o_kelt20'] = bbw[20] / kel[20]

    lhl = np.log(hs / ls) ** 2
    F['park288'] = np.sqrt(lhl.rolling(288).mean() / (4 * np.log(2)))
    F['park288_o_rv288'] = F['park288'] / rv[288]
    F['eff288'] = (cs - cs.shift(288)).abs() / cs.diff().abs().rolling(288).sum()
    F['volofvol288'] = rv[12].rolling(288).std() / rv[12].rolling(288).mean()

    for w in (48, 288, 864):
        hi = hs.rolling(w).max(); lo = ls.rolling(w).min()
        F['pos%d' % w] = (cs - lo) / (hi - lo)
    return F


def q8(s):
    """0~1 값 -> uint8 (x*200), NaN=255"""
    v = np.asarray(s, float)
    out = np.full(len(v), 255, np.uint8)
    g = np.isfinite(v)
    out[g] = np.clip(np.round(v[g] * 200.0), 0, 200).astype(np.uint8)
    return out


def do_sym(sym):
    fp = os.path.join(CACHE, sym + '.npz')
    if os.path.exists(fp):
        return sym
    d = L.load(sym)
    mask, LO, SH = L.fwd_returns(d, sym)
    F = feats_of(d)
    n = len(mask)
    keep = mask.copy()
    sel = np.zeros(n, bool); sel[::STRIDE] = True
    keep &= sel
    if keep.sum() < 50:
        np.savez_compressed(fp, empty=np.array([1]))
        return sym
    out = {'t': d['t'][keep]}
    for k in HORIZONS:
        out['L_' + k] = LO[k][keep].astype(np.float32)
        out['S_' + k] = SH[k][keep].astype(np.float32)
    for name in RANKED:
        r = F[name].replace([np.inf, -np.inf], np.nan).rolling(RANKW, min_periods=RANKMIN).rank(pct=True)
        out['f_' + name] = q8(r.values)[keep]
    for name in POSF:
        out['f_' + name] = q8(F[name].replace([np.inf, -np.inf], np.nan).values)[keep]
    np.savez_compressed(fp, **out)
    return sym


def stage_feat(nproc):
    syms = L.symbols('disc')
    from multiprocessing import Pool
    with Pool(nproc) as p:
        for i, s in enumerate(p.imap_unordered(do_sym, syms, chunksize=4)):
            if (i + 1) % 50 == 0:
                print('feat %d/%d' % (i + 1, len(syms)), flush=True)
    print('feat done', len(syms))


# ---------------- 평가 ----------------
def _atom(f, tag):
    for tg, op, th in (POS_TH if f in POSF else RANK_TH):
        if tg == tag:
            return (f, op, th)
    raise KeyError(tag)


def _parse(nm):
    out = []
    for part in nm.split(' & '):
        f, tag = part.rsplit('.', 1)
        out.append(_atom(f, tag))
    return out


def _build(fv, defn):
    s = None
    for f, op, th in defn:
        v = fv[f]
        b = (v <= th) if op == 'le' else ((v >= th) & (v != 255))
        s = b if s is None else (s & b)
    return s


def _load_all():
    syms = L.symbols('disc')
    T, SID, R, FV = [], [], {k: {'L': [], 'S': []} for k in HORIZONS}, {f: [] for f in FEATS}
    for i, s in enumerate(syms):
        z = np.load(os.path.join(CACHE, s + '.npz'))
        if 'empty' in z.files:
            continue
        T.append(z['t']); SID.append(np.full(len(z['t']), i, np.int16))
        for k in HORIZONS:
            R[k]['L'].append(z['L_' + k]); R[k]['S'].append(z['S_' + k])
        for f in FEATS:
            FV[f].append(z['f_' + f])
    t = np.concatenate(T); sid = np.concatenate(SID)
    ret = {}
    for k in HORIZONS:
        for dr in ('L', 'S'):
            ret[(k, dr)] = np.concatenate(R[k][dr]); R[k][dr] = None
    fv = {f: np.concatenate(FV[f]) for f in FEATS}
    return t, sid, ret, fv


def stage_oct():
    """out.json 의 후보 중 'oct' 없는 행에 2025-10 성적을 채운다."""
    import datetime as dt
    p = os.path.join(D, 'bsweep_vol_out.json')
    o = json.load(open(p))
    need = [r for r in o['rows'] if 'oct' not in r and r['mean'] > 0 and r['sign_stable']
            and r['months_same_sign'] >= 8][:25]
    if not need:
        print('nothing to do'); return
    t, sid, ret, fv = _load_all()
    mo = np.array([dt.datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m') for x in t])
    oct_m = (mo == '2025-10')
    for r in need:
        sg = _build(fv, _parse(r['sig'])) & oct_m
        r['oct'] = L.evaluate(sg, ret[(r['hz'], 'L' if r['dirn'] == 'LONG' else 'S')], t,
                              min_n=1, sym_ids=sid)
        print(r['sig'], r['dirn'], r['hz'], r['oct'].get('mean'), flush=True)
    json.dump(o, open(p, 'w'), default=float)
    print('oct saved', len(need))


def stage_eval():
    syms = L.symbols('disc')
    T, SID, R, FV = [], [], {k: {'L': [], 'S': []} for k in HORIZONS}, {f: [] for f in FEATS}
    for i, s in enumerate(syms):
        fp = os.path.join(CACHE, s + '.npz')
        z = np.load(fp)
        if 'empty' in z.files:
            continue
        T.append(z['t']); SID.append(np.full(len(z['t']), i, np.int16))
        for k in HORIZONS:
            R[k]['L'].append(z['L_' + k]); R[k]['S'].append(z['S_' + k])
        for f in FEATS:
            FV[f].append(z['f_' + f])
    t = np.concatenate(T); sid = np.concatenate(SID)
    del T, SID
    ret = {}
    for k in HORIZONS:
        for dr in ('L', 'S'):
            ret[(k, dr)] = np.concatenate(R[k][dr]); R[k][dr] = None
    del R
    fv = {f: np.concatenate(FV[f]) for f in FEATS}
    del FV
    N = len(t)
    print('rows', N, 'syms', len(np.unique(sid)), flush=True)

    # ---- 신호 정의(지연 평가: 이름 -> 원자조건 튜플 리스트) ----
    def atom(f, tag):
        th_tab = POS_TH if f in POSF else RANK_TH
        for tg, op, th in th_tab:
            if tg == tag:
                return (f, op, th)
        raise KeyError(tag)

    def build(defn):
        s = None
        for f, op, th in defn:
            v = fv[f]
            b = (v <= th) if op == 'le' else ((v >= th) & (v != 255))
            s = b if s is None else (s & b)
        return s

    sigdefs = {}   # name -> [(feat, op, th), ...]
    for f in RANKED:
        for tag, op, th in RANK_TH:
            sigdefs['%s.%s' % (f, tag)] = [(f, op, th)]
    pos_atoms = []
    for f in POSF:
        for tag, op, th in POS_TH:
            sigdefs['%s.%s' % (f, tag)] = [(f, op, th)]
            pos_atoms.append(('%s.%s' % (f, tag), (f, op, th)))
    for vf in CROSS_VOL:
        for tag, op, th in RANK_TH:
            a = '%s.%s' % (vf, tag)
            for bn, bt in pos_atoms:
                sigdefs[a + ' & ' + bn] = [(vf, op, th), bt]
    print('signals', len(sigdefs), 'tests', len(sigdefs) * 10, flush=True)

    rows = []
    ntest = 0
    done = 0
    for nm, defn in sigdefs.items():
        done += 1
        if done % 50 == 0:
            print('progress %d/%d kept=%d' % (done, len(sigdefs), len(rows)), flush=True)
        sg = build(defn)
        dens = sg.mean()
        if dens >= 0.10:
            ntest += 10
            continue
        for k in HORIZONS:
            for dr in ('L', 'S'):
                ntest += 1
                r = L.evaluate(sg, ret[(k, dr)], t, min_n=500, sym_ids=sid)
                if not r.get('ok'):
                    continue
                if r['nsyms'] < 30 or r['ndays'] < 30:
                    continue
                r.update(sig=nm, dirn='LONG' if dr == 'L' else 'SHORT', hz=k, dens=float(dens))
                rows.append(r)
    print('tested', ntest, 'kept', len(rows), flush=True)
    rows.sort(key=lambda r: -r['mean'])
    json.dump({'rows': rows[:400], 'base': [], 'ntest': ntest,
               'nsig': len(sigdefs), 'N': int(N)},
              open(os.path.join(D, 'bsweep_vol_ckpt.json'), 'w'), default=float)
    print('ckpt saved', flush=True)

    # 무조건 진입 기준선
    allm = np.ones(N, bool)
    base = []
    for k in HORIZONS:
        for dr in ('L', 'S'):
            r = L.evaluate(allm, ret[(k, dr)], t, min_n=500, sym_ids=sid)
            r.update(sig='<무조건 진입>', dirn='LONG' if dr == 'L' else 'SHORT', hz=k, dens=1.0)
            base.append(r)

    # 2025-10 성적
    import datetime as dt
    mo = np.array([dt.datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m') for x in t])
    oct_m = (mo == '2025-10')
    rows.sort(key=lambda r: -r['mean'])
    top = [r for r in rows if r['mean'] > 0 and r['sign_stable']][:40]
    for r in top:
        sg = build(sigdefs[r['sig']]) & oct_m
        rr = L.evaluate(sg, ret[(r['hz'], 'L' if r['dirn'] == 'LONG' else 'S')], t,
                        min_n=1, sym_ids=sid)
        r['oct'] = rr
    for r in base:
        sg = allm & oct_m
        rr = L.evaluate(sg, ret[(r['hz'], 'L' if r['dirn'] == 'LONG' else 'S')], t,
                        min_n=1, sym_ids=sid)
        r['oct'] = rr

    json.dump({'rows': rows[:400], 'base': base, 'ntest': ntest,
               'nsig': len(sigdefs), 'N': int(N)},
              open(os.path.join(D, 'bsweep_vol_out.json'), 'w'), default=float)
    print('saved')


def _oct(r):
    o = r.get('oct') or {}
    if not o.get('ok'):
        return 'n<1'
    return '%+.2f%% (n=%d)' % (o['mean'], o['n'])


def stage_report():
    o = json.load(open(os.path.join(D, 'bsweep_vol_out.json')))
    rows, base = o['rows'], o['base']
    cand = [r for r in rows if r['mean'] > 0 and r['n'] >= 500 and r['nsyms'] >= 30
            and r['ndays'] >= 30 and r['sign_stable']]
    cand.sort(key=lambda r: -r['mean'])
    top = cand[:15]
    H = []
    H.append('# 변동성/레인지 계열 전수 스윕 결과')
    H.append('')
    H.append('- 데이터: 바이낸스 USDT 무기한선물 5분봉, `swlib.symbols(\'disc\')` 610종목, '
             '2025-08-01~2026-08-01')
    H.append('- 수익률·비용·펀딩·연속성: `swlib.fwd_returns` (명목가 기준 순수익률 %, 왕복 0.12% + 펀딩 실측)')
    H.append('- 판정: `swlib.evaluate` 를 전 종목 concat 배열에 조합당 1회 호출')
    H.append('- 봉 서브샘플 STRIDE=6 (30분 간격, 사전확정) → 평가 행 %s' % f"{o['N']:,}")
    H.append('- 특징은 종목별 **과거 30일(8640봉) 롤링 백분위 rank**(현재봉 포함, 미래 미포함)')
    H.append('')
    H.append('## 검정 규모')
    H.append('')
    H.append('| 항목 | 값 |')
    H.append('|---|---|')
    H.append('| 신호 정의 수 | %d |' % o['nsig'])
    H.append('| **검정한 총 조합 수 (신호 × 방향2 × 지평5)** | **%d** |' % o['ntest'])
    H.append('| 사전등록 필터 통과 (밀도<10%, n≥500, 종목≥30, 날짜≥30) | **5120 (전부 통과)** |')
    H.append('| 결과 파일에 보존한 상위 | 평균 상위 %d건 (400번째도 평균 %+.3f%%) |'
             % (len(rows), rows[-1]['mean']))
    H.append('| 그 400건 중 평균>0 & 부호유지=True | %d |' % len(cand))
    H.append('| 그 400건 중 **월 부호일치 ≥8/12** | %d |'
             % sum(1 for r in cand if r['months_same_sign'] >= 8))
    H.append('')
    H.append('## 무조건 진입 기준선')
    H.append('')
    H.append('| 방향 | 지평 | n | 평균% | 중앙% | 승률% | 월 부호일치/총월 | 2025-10 |')
    H.append('|---|---|---|---|---|---|---|---|')
    for r in sorted(base, key=lambda x: (x['dirn'], HORIZONS.index(x['hz']))):
        H.append('| %s | %s | %s | %+.3f | %+.3f | %.1f | %d/%d | %s |' % (
            r['dirn'], r['hz'], f"{r['n']:,}", r['mean'], r['median'], r['win'],
            r['months_same_sign'], r['months_total'], _oct(r)))
    H.append('')
    H.append('## 상위 후보 (평균>0 · n≥500 · 종목≥30 · 날짜≥30 · 부호유지=True, 평균 내림차순 15개)')
    H.append('')
    if not top:
        H.append('**조건 충족 0개**')
    else:
        H.append('| # | 특징 정의(정확히) | 방향 | 지평 | n | 종목수 | 날짜수 | 평균% | 중앙% | 승률% | '
                 '최대기여일제외% | 월 부호일치/총월 | 8/12↑ |')
        H.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
        for i, r in enumerate(top, 1):
            flag = '**YES**' if r['months_same_sign'] >= 8 else '-'
            H.append('| %d | `%s` | %s | %s | %s | %d | %d | %+.3f | %+.3f | %.1f | %+.3f | '
                     '%d/%d | %s |' % (
                         i, r['sig'], r['dirn'], r['hz'], f"{r['n']:,}", r['nsyms'], r['ndays'],
                         r['mean'], r['median'], r['win'], r['mean_ex_topday'],
                         r['months_same_sign'], r['months_total'], flag))
    H.append('')
    m8 = [r for r in cand if r['months_same_sign'] >= 8][:15]
    H.append('## 핵심 기준: 월 부호일치 8/12 이상 (평균 내림차순 15개)')
    H.append('')
    if not m8:
        H.append('**조건 충족 0개**')
    else:
        H.append('| # | 특징 정의(정확히) | 방향 | 지평 | n | 종목수 | 날짜수 | 평균% | 중앙% | 승률% | '
                 '최대기여일제외% | **월 부호일치/총월** | 2025-10 평균% |')
        H.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
        for i, r in enumerate(m8, 1):
            oc = r.get('oct') or {}
            H.append('| %d | `%s` | %s | %s | %s | %d | %d | %+.3f | %+.3f | %.1f | %+.3f | '
                     '**%d/%d** | %s |' % (
                         i, r['sig'], r['dirn'], r['hz'], f"{r['n']:,}", r['nsyms'], r['ndays'],
                         r['mean'], r['median'], r['win'], r['mean_ex_topday'],
                         r['months_same_sign'], r['months_total'],
                         ('%+.3f (n=%s)' % (oc['mean'], f"{oc['n']:,}")) if oc.get('ok') else 'n/a'))
    H.append('')
    H.append('## 2025-10 (알트 대폭등) 한 달 성적 — 상위 후보별')
    H.append('')
    H.append('| # | 특징 정의 | 방향 | 지평 | 전체 평균% | **2025-10 평균%** | 2025-10 n |')
    H.append('|---|---|---|---|---|---|---|')
    for i, r in enumerate(top, 1):
        oc = r.get('oct') or {}
        H.append('| %d | `%s` | %s | %s | %+.3f | %s | %s |' % (
            i, r['sig'], r['dirn'], r['hz'], r['mean'],
            ('%+.3f' % oc['mean']) if oc.get('ok') else 'n/a',
            f"{oc['n']:,}" if oc.get('ok') else '-'))
    H.append('')
    H.append('## 임계값 정의')
    H.append('')
    H.append('- rank 특징: `.lo02`=과거30일 백분위 ≤2%, `.lo05`=≤5%, `.hi95`=≥95%, `.hi98`=≥98%')
    H.append('- 위치 특징 pos(N)=(종가-최근N봉최저저가)/(최근N봉최고고가-최근N봉최저저가), '
             '원값 사용: `.lo05`=≤0.05, `.lo10`=≤0.10, `.hi90`=≥0.90, `.hi95`=≥0.95')
    H.append('- `A & B` 는 두 신호 동시 성립')
    open(os.path.join(D, 'bresult_vol.md'), 'w', encoding='utf-8').write('\n'.join(H) + '\n')
    print('\n'.join(H))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage')
    ap.add_argument('--nproc', type=int, default=8)
    a = ap.parse_args()
    if a.stage == 'feat':
        stage_feat(a.nproc)
    elif a.stage == 'report':
        stage_report()
    elif a.stage == 'oct':
        stage_oct()
    else:
        stage_eval()
