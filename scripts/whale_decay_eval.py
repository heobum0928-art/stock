"""PREREG_WHALE_DECAY.md 실행 — 고래 프린트 효과의 단기 감쇠 곡선.

Run: .venv/Scripts/python.exe scripts/whale_decay_eval.py
"""
import csv, sys
from datetime import datetime
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

COST = 0.12
HS = [(30, "30초"), (60, "1분"), (120, "2분"), (300, "5분"),
      (600, "10분"), (1800, "30분"), (3600, "60분")]
MAX_BASE_LAG = 60
SEED, BOOT, BLOCK_DAYS = 20260918, 4000, 7


def load():
    wh = {}
    with open("data/whale_print_events.csv", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timestamp()
                s = r["side"].strip()
                if s not in ("bid", "ask"):
                    continue
            except Exception:
                continue
            wh.setdefault(r["coin"], []).append((t, s))
    of = {}
    with open("data/orderflow_events.csv", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timestamp()
                p = float(r["price"])
                if p <= 0:
                    continue
            except Exception:
                continue
            of.setdefault(r["coin"], []).append((t, p))
    for d in (wh, of):
        for c in d:
            d[c].sort()
    return wh, of


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


def curve(wh, of, H, skip_btc=False):
    rb, ra, db, da, lags = [], [], [], [], []
    for coin, rows in wh.items():
        if skip_btc and coin == "BTC":
            continue
        o = of.get(coin)
        if not o:
            continue
        ot = np.array([x[0] for x in o]); op = np.array([x[1] for x in o])
        wt = np.array([x[0] for x in rows])
        i0 = np.searchsorted(ot, wt, side="right") - 1
        i1 = np.searchsorted(ot, wt + H, side="left")
        for n in range(len(rows)):
            a, b = i0[n], i1[n]
            if a < 0 or b >= len(ot):
                continue
            if wt[n] - ot[a] > MAX_BASE_LAG or ot[b] - wt[n] > 2 * H:
                continue
            if op[a] <= 0:
                continue
            ret = (op[b] / op[a] - 1) * 100
            d = int(wt[n] // 86400)
            lags.append(wt[n] - ot[a])
            if rows[n][1] == "bid":
                rb.append(ret); db.append(d)
            else:
                ra.append(ret); da.append(d)
    return (np.array(rb), np.array(db), np.array(ra), np.array(da),
            float(np.mean(lags)) if lags else float("nan"))


def main():
    wh, of = load()
    print("[고래 프린트 단기 감쇠] 사전등록 docs/PREREG_WHALE_DECAY.md (커밋 5ed3110)")
    print("매매 판정 아님 — (가) 아예 없다 / (나) 있었는데 못 먹는다 를 가르는 진단.\n")
    print(f"{'구간':>5} {'매칭':>9} {'bid평균':>10} {'ask평균':>10} {'차이':>10} {'95% CI':>22} {'지연':>6}")
    peak, peak_h = 0.0, None
    signs = []
    for H, lab in HS:
        rb, db, ra, da, lag = curve(wh, of, H)
        if len(rb) < 500 or len(ra) < 500:
            print(f"{lab:>5} {len(rb)+len(ra):>9,}  표본 부족"); continue
        d = rb.mean() - ra.mean()
        lo, hi = boot_diff(rb, db, ra, da)
        signs.append(np.sign(d))
        if abs(d) > abs(peak):
            peak, peak_h = d, lab
        print(f"{lab:>5} {len(rb)+len(ra):>9,} {rb.mean():>+9.4f}% {ra.mean():>+9.4f}% "
              f"{d:>+9.4f}%p [{lo:>+8.4f},{hi:>+8.4f}] {lag:>5.0f}s")

    print("\n" + "=" * 78)
    print(f"  곡선 최대 |차이| = {abs(peak):.4f}%p  ({peak_h})   왕복 비용 {COST}%p")
    if abs(peak) < COST:
        print(f"  ▶ **(가) 아예 없다** — 어떤 구간에서도 비용을 넘지 못한다.")
        print(f"     최대값이 비용의 {abs(peak)/COST*100:.0f}%에 그친다.")
    else:
        print(f"  ▶ **(나) 있었는데 못 먹는다** — {peak_h}에서 비용의 {abs(peak)/COST:.2f}배.")
        print(f"     우리 봇은 REST 5초 폴링이고 빗썸 현물 신호로 바이낸스 선물을 친다.")
        print(f"     {peak_h} 안에 진입·청산이 가능한 구조가 아니다.")
    if len(set(signs)) > 1:
        print("  ※ 구간에 따라 부호가 뒤집힌다 — 안정적 방향성이 없다는 뜻.")

    print("\n  [병기] BTC 제외 곡선:")
    for H, lab in HS:
        rb, db, ra, da, _ = curve(wh, of, H, skip_btc=True)
        if len(rb) < 500 or len(ra) < 500:
            continue
        print(f"    {lab:>4}: {rb.mean()-ra.mean():+.4f}%p ({len(rb)+len(ra):,}건)")

    print("\n  ※ 이 결과로 주문 로직을 만들지 않는다 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
