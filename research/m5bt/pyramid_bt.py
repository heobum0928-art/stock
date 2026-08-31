"""PREREG_PYRAMID.md 검증 — 불타기(피라미딩) vs 현행, 2,399건 짝비교.

engine.py의 scan/evaluate는 고정 사이즈 단일 포지션 전제라 그대로는 불타기를 못 담는다
(PREREG_PYRAMID.md 2절에서 확인). 여기서는 같은 신호셋(signals.py의 7h+30~40%, 원본
margin_short 신호)에 대해 봉 단위로 직접 시뮬레이션한다.

정확성 검증: add_trig를 도달 불가능한 값(9999%)으로 두면 이 스크립트의 결과이
engine.py의 scan/evaluate 결과와 정확히 일치해야 한다(__main__ 하단 자체 회귀검증).

규칙(PREREG_PYRAMID.md 1절, 변경 금지):
  트리거 = 명목가 25% 유리, 추가량 = 원증거금 50%, 1회만, 손실 중 추가 금지(트리거 자체가
  유리한 쪽이라 자동 충족), 추가 후 평균단가로 손절(-40%)·트레일링(15%/10%) 재계산.
  손익은 레그별 실제 진입가 기준으로 계산한다(평균단가는 트리거 산정에만 쓴다 — 실제
  거래에서 이미 보유한 물량의 원가는 소급해서 안 바뀐다).
"""
import os, glob, hashlib
import numpy as np
import engine as E
from signals import sigs_for

D = os.path.dirname(os.path.abspath(__file__))
PQ = os.path.join(D, "pq")
HOLD_BARS = 576              # 48h — 변경 금지
STOP_PCT = 40.0
TRAIL_TRIG = 15.0
TRAIL_GIVE = 10.0
ADD_TRIG = 25.0               # PREREG_PYRAMID.md 1절
ADD_FRAC = 0.5
LEV = E.LEV
FEE_SIDE = E.FEE_SIDE
STOP_EXTRA = E.STOP_EXTRA


def holdout(sym):
    return int(hashlib.md5(sym.encode()).hexdigest(), 16) % 4 == 0


def cumfund_for(sym, t0, bt):
    p = os.path.join(D, "fund", sym + ".npz")
    if not os.path.exists(p):
        return np.zeros(len(bt), np.float64)
    z = np.load(p)
    ft = z[z.files[0]]; fr = z[z.files[1]]
    cs = np.concatenate(([0.0], np.cumsum(fr)))
    lo = np.searchsorted(ft, t0, side="right")
    hi = np.searchsorted(ft, bt, side="right")
    return cs[hi] - cs[lo]


def simulate(o, h, l, c, cf, P0, add_trig=ADD_TRIG, add_frac=ADD_FRAC,
             stop_pct=STOP_PCT, trail_trig=TRAIL_TRIG, trail_give=TRAIL_GIVE):
    """봉 단위 직접 시뮬레이션. engine.scan()의 opt=True 서브패스(open,low,high,close)와
    '위쪽 이동=역행(숏 불리) / 아래쪽 이동=순행(숏 유리)' 판정 규칙을 그대로 따른다.
    add_trig를 도달 불가능한 값으로 두면 engine.scan()+evaluate()와 동일 결과가 나와야
    한다(회귀검증 대상)."""
    n = len(c)
    avg_entry = P0
    qty = 1.0
    added = False
    add_price = None
    add_qty = 0.0
    peak_fav = 0.0
    prev = P0
    stop_price = avg_entry * (1 + stop_pct / 100.0)
    trail_arm = False
    exit_info = None

    for i in range(n):
        path = (o[i], l[i], h[i], c[i])   # opt=True와 동일 순서
        for k in range(4):
            nxt = path[k]
            gap = (k == 0)
            if nxt > prev:
                # ── 역행(숏 불리) 방향 이동: 트레일링 청산은 "다시 올라올 때"
                #    발동한다(트레일링선은 진입가 아래, 즉 순행 쪽 가격) — engine.scan()과
                #    동일하게 이 분기에서 먼저 검사한다(트레일링이 손절보다 항상 먼저 걸림).
                if trail_arm:
                    tl_price = avg_entry * (1 - (peak_fav - trail_give) / 100.0)
                    if tl_price <= prev:
                        exit_info = (i, prev, 'trail'); break
                    elif tl_price <= nxt:
                        exit_info = (i, nxt if gap else tl_price, 'trail'); break
                if stop_price <= prev:
                    exit_info = (i, prev, 'stop'); break
                elif stop_price <= nxt:
                    exit_info = (i, nxt if gap else stop_price, 'stop'); break
            else:
                # ── 순행(숏 유리) 방향 이동: 최고순행폭 갱신 + 불타기 트리거만 여기서 ──
                fav = (1 - nxt / avg_entry) * 100.0
                if fav > peak_fav:
                    peak_fav = fav
                if peak_fav >= trail_trig:
                    trail_arm = True
                if not added and peak_fav >= add_trig:
                    ap = avg_entry * (1 - add_trig / 100.0)
                    if gap and ap > nxt:
                        ap = nxt
                    add_price = ap; add_qty = add_frac
                    new_qty = qty + add_frac
                    avg_entry = (avg_entry * qty + ap * add_frac) / new_qty
                    qty = new_qty
                    added = True
                    stop_price = avg_entry * (1 + stop_pct / 100.0)
                    peak_fav = max(0.0, (1 - nxt / avg_entry) * 100.0)
                    trail_arm = peak_fav >= trail_trig
            prev = nxt
        if exit_info is not None:
            break
    if exit_info is None:
        exit_info = (n - 1, c[n - 1], 'expiry')

    bar_i, fill_px, kind = exit_info
    legs = [(P0, 1.0)] + ([(add_price, add_qty)] if added else [])
    total_qty = sum(q for _, q in legs)

    tot_orig = 0.0
    tot_cap = 0.0
    for entry_px, q in legs:
        leg_ret = -LEV * (fill_px / entry_px - 1.0) - LEV * FEE_SIDE * 2   # 진입+청산 편도 수수료
        if kind != 'expiry':
            leg_ret -= LEV * STOP_EXTRA
        tot_cap += leg_ret * q
        if entry_px == P0:
            tot_orig += leg_ret

    # 펀딩비: qty 비례 배분(추가분도 전체기간 낸 것으로 근사 — 실제보다 약간 불리하게
    # 계상되므로, 이 방향으로 결과가 나쁘게 나온다면 실제는 더 낫다는 뜻이라 안전한 근사).
    if cf is not None and bar_i < len(cf):
        fnd = float(cf[bar_i])
        tot_cap += LEV * total_qty * fnd
        tot_orig += LEV * 1.0 * fnd

    tot_cap = max(tot_cap, -total_qty)     # 격리증거금 100% 초과손실 불가
    tot_orig = max(tot_orig, -1.0)

    return dict(ret_cap=tot_cap / total_qty * 100.0, ret_orig=tot_orig * 100.0,
                added=added, kind=kind, exit_bar=bar_i, total_qty=total_qty)


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"

    if mode == "verify":
        # 회귀검증: add_trig=9999(도달불가) 시 engine.scan/evaluate와 정확히 일치해야 함.
        print("=== 자체 회귀검증: add_trig=9999(불타기 없음) vs engine.py ===")
        syms = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ, "*.npz")))[:60]
        checked = 0; maxdiff = 0.0
        for s in syms:
            sg, arr = sigs_for(s)
            if not sg:
                continue
            t, o, h, l, c, qv = arr
            for (i, ts, px, ret7, v24) in sg:
                P0 = float(c[i]); j = min(i + 1 + HOLD_BARS, len(c))
                if j - (i + 1) < 12:
                    continue
                sl = slice(i + 1, j)
                hh, ll, oo, cc, bt = h[sl], l[sl], o[sl], c[sl], t[sl]
                cf = cumfund_for(s, int(t[i]), bt)
                f, tr, ex, mae, mfe = E.scan(hh, ll, oo, cc, P0, opt=True)
                se = E.SigEvents(f, tr, ex, mae, mfe, P0, int(t[i]), bt, len(cc))
                se.cumfund = cf.astype(np.float32)
                r_eng = E.evaluate(se, None, 0.0, 40.0, 40.0, funding_fn=E.funding)
                r_mine = simulate(oo, hh, ll, cc, cf, P0, add_trig=9999.0)
                diff = abs(r_eng['ret'] * 100.0 - r_mine['ret_orig'])
                maxdiff = max(maxdiff, diff)
                checked += 1
                if diff > 0.05:
                    print(f"  불일치 {s} bar{i}: engine={r_eng['ret']*100:+.3f}% "
                          f"mine={r_mine['ret_orig']:+.3f}% (diff {diff:.3f})")
        print(f"검증 {checked}건, 최대 오차 {maxdiff:.4f}%p")
        print("PASS" if maxdiff < 0.05 else "FAIL — 로직 재검토 필요")

    elif mode == "run":
        print("=== 불타기(+25%,50%,1회) vs 현행 — 2,399건 짝비교 ===")
        syms = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ, "*.npz")))
        rows = []
        for si, s in enumerate(syms):
            sg, arr = sigs_for(s)
            if not sg:
                continue
            t, o, h, l, c, qv = arr
            for (i, ts, px, ret7, v24) in sg:
                P0 = float(c[i]); j = min(i + 1 + HOLD_BARS, len(c))
                if j - (i + 1) < 12:
                    continue
                sl = slice(i + 1, j)
                hh, ll, oo, cc, bt = h[sl], l[sl], o[sl], c[sl], t[sl]
                cf = cumfund_for(s, int(t[i]), bt)
                r0 = simulate(oo, hh, ll, cc, cf, P0, add_trig=9999.0)
                r1 = simulate(oo, hh, ll, cc, cf, P0)
                rows.append((s, int(ts), holdout(s), r0['ret_orig'], r1['ret_orig'],
                             r1['ret_cap'], r1['added'], r1['kind']))
            if (si + 1) % 200 == 0:
                print(f"  {si+1}/{len(syms)} 종목, 신호 {len(rows)}건", flush=True)
        import pickle
        pickle.dump(rows, open(os.path.join(D, "pyramid_result.pkl"), "wb"))
        print(f"완료: {len(rows)}건 → pyramid_result.pkl")

    elif mode == "run_notrail":
        # 2026-08-31: 실거래 margin_short_trader.py의 트레일링을 껐다(PREREG_V1_NOTRAIL.md
        # 판정 통과). 원래 불타기 검정(위 run)은 트레일링이 있는 V0_base를 기준으로 했고,
        # 기각 사유(짝차이 -0.27%p)가 발동 307건의 청산유형 전부(215 trail + 92 expiry,
        # stop 0건)에서 나왔다 — 즉 기각은 거의 전적으로 트레일링의 부작용이었다. 트레일링을
        # 뺀 새 기준선(손절 -40%+48h만기만)으로 같은 신호셋에 다시 짝비교한다. 트리거(+25%)·
        # 추가량(50%)·손절폭(40%) 등 PREREG_PYRAMID.md 1절의 규칙 자체는 바꾸지 않는다 —
        # 바뀐 건 "비교 대상 기준선(트레일링 유무)"뿐이다.
        print("=== 불타기(+25%,50%,1회) vs 현행(트레일링 없음) — 2,399건 짝비교 ===")
        syms = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ, "*.npz")))
        rows = []
        for si, s in enumerate(syms):
            sg, arr = sigs_for(s)
            if not sg:
                continue
            t, o, h, l, c, qv = arr
            for (i, ts, px, ret7, v24) in sg:
                P0 = float(c[i]); j = min(i + 1 + HOLD_BARS, len(c))
                if j - (i + 1) < 12:
                    continue
                sl = slice(i + 1, j)
                hh, ll, oo, cc, bt = h[sl], l[sl], o[sl], c[sl], t[sl]
                cf = cumfund_for(s, int(t[i]), bt)
                r0 = simulate(oo, hh, ll, cc, cf, P0, add_trig=9999.0, trail_trig=9999.0)
                r1 = simulate(oo, hh, ll, cc, cf, P0, trail_trig=9999.0)
                rows.append((s, int(ts), holdout(s), r0['ret_orig'], r1['ret_orig'],
                             r1['ret_cap'], r1['added'], r1['kind']))
            if (si + 1) % 200 == 0:
                print(f"  {si+1}/{len(syms)} 종목, 신호 {len(rows)}건", flush=True)
        import pickle
        pickle.dump(rows, open(os.path.join(D, "pyramid_result_notrail.pkl"), "wb"))
        print(f"완료: {len(rows)}건 → pyramid_result_notrail.pkl")
