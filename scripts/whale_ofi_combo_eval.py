"""PREREG_WHALE_OFI_COMBO.md 실행 — 고래 프린트 × OFI 부호 결합 신호.

외부 API 호출 없음.
Run: .venv/Scripts/python.exe scripts/whale_ofi_combo_eval.py
"""
import csv, sys
from datetime import datetime
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WH = "data/whale_print_events.csv"
OF = "data/orderflow_events.csv"
H = 3600
LOOKBACK = 300        # OFI 매칭 창 (직전 5분)
COST = 0.12
SOLO = 0.0706         # 단독 검정 결과(2026-09-18, 커밋 5031abc)
SEED, BOOT, BLOCK_DAYS = 20260918, 4000, 7


def load_whale():
    per = {}
    with open(WH, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timestamp()
                p = float(r["price"]); s = r["side"].strip()
                if p <= 0 or s not in ("bid", "ask"):
                    continue
            except Exception:
                continue
            per.setdefault(r["coin"], []).append((t, p, s))
    for c in per:
        per[c].sort()
    return per


def load_ofi():
    per = {}
    with open(OF, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timestamp()
                o = float(r["ofi"])
            except Exception:
                continue
            per.setdefault(r["coin"], []).append((t, o))
    for c in per:
        per[c].sort()
    return per


def blocks_idx(days):
    b = (days - days.min()) // BLOCK_DAYS
    ub = np.unique(b)
    return ub, {u: np.nonzero(b == u)[0] for u in ub}


def boot_diff(x1, d1, x2, d2, seed=SEED, iters=BOOT):
    u1, i1 = blocks_idx(d1)
    u2, i2 = blocks_idx(d2)
    rng = np.random.default_rng(seed)
    ms = np.empty(iters)
    for k in range(iters):
        s1 = np.concatenate([i1[u1[p]] for p in rng.integers(0, len(u1), len(u1))])
        s2 = np.concatenate([i2[u2[p]] for p in rng.integers(0, len(u2), len(u2))])
        ms[k] = x1[s1].mean() - x2[s2].mean()
    return np.percentile(ms, [2.5, 97.5])


def main():
    wh = load_whale()
    of = load_ofi()
    print("[고래 × OFI 결합] 사전등록 docs/PREREG_WHALE_OFI_COMBO.md (커밋 9cc0ed5)")
    print(f"고래 {sum(len(v) for v in wh.values()):,}건 / OFI {sum(len(v) for v in of.values()):,}행. "
          f"외부 API 없음.\n")

    recs = []
    n_no_ofi = 0
    lags = []
    for coin, rows in wh.items():
        ts = np.array([x[0] for x in rows]); px = np.array([x[1] for x in rows])
        j = np.searchsorted(ts, ts + H, side="left")
        ot = np.array([x[0] for x in of.get(coin, [])])
        ov = np.array([x[1] for x in of.get(coin, [])])
        for i in range(len(rows)):
            k = j[i]
            if k >= len(rows) or ts[k] - ts[i] > 2 * H:
                continue
            if not len(ot):
                n_no_ofi += 1; continue
            m = np.searchsorted(ot, ts[i], side="right") - 1
            if m < 0 or ts[i] - ot[m] > LOOKBACK:
                n_no_ofi += 1; continue
            lags.append(ts[i] - ot[m])
            ret = (px[k] / px[i] - 1) * 100
            recs.append((ts[i], coin, rows[i][2], float(ov[m]), ret))

    tot_matched = len(recs) + n_no_ofi
    print(f"1시간 수익률 매칭 후 {tot_matched:,}건 → OFI 5분 내 매칭 {len(recs):,}건 "
          f"({len(recs)/tot_matched*100:.1f}%), 평균 지연 {np.mean(lags):.0f}초")
    print(f"단독 검정 대비 표본 {len(recs)/219273*100:.1f}%\n")

    buy = [r for r in recs if r[2] == "bid" and r[3] > 0]
    sell = [r for r in recs if r[2] == "ask" and r[3] < 0]
    if len(buy) < 5000 or len(sell) < 5000:
        print(f"  ▶ X5: 표본 부족 (강한매수 {len(buy):,} / 강한매도 {len(sell):,}) — 판정 보류")
        return

    xb = np.array([r[4] for r in buy]); db = np.array([int(r[0] // 86400) for r in buy])
    xs = np.array([r[4] for r in sell]); ds = np.array([int(r[0] // 86400) for r in sell])
    diff = xb.mean() - xs.mean()
    lo, hi = boot_diff(xb, db, xs, ds)

    print(f"  강한 매수 (bid & ofi>0)  {len(buy):>7,}건  평균 {xb.mean():+.4f}%  중앙 {np.median(xb):+.4f}%")
    print(f"  강한 매도 (ask & ofi<0)  {len(sell):>7,}건  평균 {xs.mean():+.4f}%  중앙 {np.median(xs):+.4f}%")
    print(f"\n  차이 = {diff:+.4f}%p")
    print(f"  95% CI [{lo:+.4f}, {hi:+.4f}]  — {BLOCK_DAYS}일 블록, {BOOT}회, 시드 {SEED}")
    print(f"  왕복 비용 {COST}%p / X1 문턱 {COST*2}%p / 단독 결과 {SOLO:+.4f}%p")

    if lo <= 0 <= hi:
        v = "판별 불가 (X4)"
    elif abs(diff) >= COST * 2:
        v = "쓸 만한 결합 신호 (X1)"
    elif abs(diff) >= COST:
        v = "존재하나 비용 대비 얇음 (X2)"
    else:
        v = "쓸 수 없음 (X3)"
    print(f"\n  ▶ 판정: {v}")
    if diff <= SOLO:
        print(f"  ▶ 추가 조건: 단독({SOLO:+.4f}%p) 이하 → **결합의 이득 없음**")
    else:
        print(f"  ▶ 추가 조건: 단독 대비 {diff - SOLO:+.4f}%p 개선")

    print("\n" + "=" * 70)
    print("[병기 — 판정에 쓰지 않음]")
    for lab, sel in (("bid & ofi>0", lambda r: r[2] == "bid" and r[3] > 0),
                     ("bid & ofi<0", lambda r: r[2] == "bid" and r[3] < 0),
                     ("ask & ofi<0", lambda r: r[2] == "ask" and r[3] < 0),
                     ("ask & ofi>0", lambda r: r[2] == "ask" and r[3] > 0)):
        g = [r[4] for r in recs if sel(r)]
        if len(g) < 500:
            print(f"    {lab:<12} {len(g):>7,}건 — 부족"); continue
        print(f"    {lab:<12} {len(g):>7,}건  평균 {np.mean(g):+.4f}%")

    cc = {}
    for r in recs:
        cc[r[1]] = cc.get(r[1], 0) + 1
    top = sorted(cc.items(), key=lambda z: -z[1])[:3]
    print("\n  코인 쏠림: " + ", ".join(f"{c} {n:,}({n/len(recs)*100:.1f}%)" for c, n in top))
    nb_b = [r[4] for r in buy if r[1] != "BTC"]; nb_s = [r[4] for r in sell if r[1] != "BTC"]
    if len(nb_b) > 500 and len(nb_s) > 500:
        print(f"  BTC 제외 차 {np.mean(nb_b)-np.mean(nb_s):+.4f}%p")

    print("\n  ※ 통과해도 주문 로직 아님 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
