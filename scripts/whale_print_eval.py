"""PREREG_WHALE_PRINT.md 실행 — 고래 대량체결(bid/ask) 이후 수익률 차이.

외부 API 호출 없음. 미래 가격은 같은 이벤트 스트림에서 구한다.
Run: .venv/Scripts/python.exe scripts/whale_print_eval.py
"""
import csv, sys
from datetime import datetime
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = "data/whale_print_events.csv"
COST = 0.12            # 왕복 명목 %
MAIN_H = 3600
HORIZONS = [(300, "5분"), (900, "15분"), (3600, "1시간"), (14400, "4시간")]
SEED, BOOT, BLOCK_DAYS = 20260918, 4000, 7


def load():
    per = {}
    with open(SRC, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timestamp()
                p = float(r["price"])
                side = r["side"].strip()
                if p <= 0 or side not in ("bid", "ask"):
                    continue
                rec = (t, p, side, float(r.get("ratio_to_median") or 0),
                       float(r.get("range_pos_2h") or np.nan))
            except Exception:
                continue
            per.setdefault(r["coin"], []).append(rec)
    for c in per:
        per[c].sort()
    return per


def build(per, H):
    """각 이벤트의 H 이후 수익률. 경과 > 2H면 버린다."""
    out = []
    for coin, rows in per.items():
        ts = np.array([x[0] for x in rows])
        px = np.array([x[1] for x in rows])
        j = np.searchsorted(ts, ts + H, side="left")
        for i in range(len(rows)):
            k = j[i]
            if k >= len(rows):
                continue
            el = ts[k] - ts[i]
            if el > 2 * H:
                continue
            ret = (px[k] / px[i] - 1) * 100
            out.append((ts[i], coin, rows[i][2], ret, rows[i][3], rows[i][4], el))
    return out


def blocks_idx(days):
    b = (days - days.min()) // BLOCK_DAYS
    ub = np.unique(b)
    return ub, {u: np.nonzero(b == u)[0] for u in ub}


def boot_diff(rb, db, ra, da, seed=SEED, iters=BOOT):
    ub1, i1 = blocks_idx(db)
    ub2, i2 = blocks_idx(da)
    rng = np.random.default_rng(seed)
    ms = np.empty(iters)
    for k in range(iters):
        s1 = np.concatenate([i1[ub1[p]] for p in rng.integers(0, len(ub1), len(ub1))])
        s2 = np.concatenate([i2[ub2[p]] for p in rng.integers(0, len(ub2), len(ub2))])
        ms[k] = rb[s1].mean() - ra[s2].mean()
    return np.percentile(ms, [2.5, 97.5])


def split(rows):
    b = np.array([x[3] for x in rows if x[2] == "bid"])
    a = np.array([x[3] for x in rows if x[2] == "ask"])
    db = np.array([int(x[0] // 86400) for x in rows if x[2] == "bid"])
    da = np.array([int(x[0] // 86400) for x in rows if x[2] == "ask"])
    return b, db, a, da


def main():
    per = load()
    tot = sum(len(v) for v in per.values())
    print("[고래 대량체결 예측력] 사전등록 docs/PREREG_WHALE_PRINT.md (커밋 2eabb69)")
    print(f"이벤트 {tot:,}건, 코인 {len(per)}종. 외부 API 호출 없음.")
    print(f"판정 기준은 **크기**다 — 왕복 비용 {COST}%(명목)를 넘는가. 유의성은 보조.\n")

    rows = build(per, MAIN_H)
    print(f"주 구간 1시간: 매칭 {len(rows):,}건 / {tot:,}건 ({len(rows)/tot*100:.1f}%)")
    if len(rows) < 10000:
        print("  ▶ W5: 매칭 10,000건 미만 — 판정 보류"); return

    b, db, a, da = split(rows)
    diff = b.mean() - a.mean()
    lo, hi = boot_diff(b, db, a, da)
    el = np.mean([x[6] for x in rows]) / 60
    print(f"  bid(고래 매수) {len(b):,}건  평균 {b.mean():+.4f}%  중앙 {np.median(b):+.4f}%")
    print(f"  ask(고래 매도) {len(a):,}건  평균 {a.mean():+.4f}%  중앙 {np.median(a):+.4f}%")
    print(f"  평균 경과 {el:.1f}분 (목표 60분)")
    print(f"\n  차이(bid−ask) = {diff:+.4f}%p")
    print(f"  95% CI [{lo:+.4f}, {hi:+.4f}]  — {BLOCK_DAYS}일 블록, {BOOT}회, 시드 {SEED}")
    print(f"  왕복 비용 {COST}%p / 그 2배 {COST*2}%p")

    ci0 = (lo <= 0 <= hi)
    if ci0:
        v = "판별 불가 (W4)"
    elif abs(diff) >= COST * 2:
        v = "쓸 만한 신호 (W1)"
    elif abs(diff) >= COST:
        v = "존재하나 비용 대비 얇음 (W2)"
    else:
        v = "쓸 수 없음 — 유의해도 비용을 못 넘는다 (W3)"
    print(f"\n  ▶ 판정: {v}")

    # ===== 병기 =====
    print("\n" + "=" * 70)
    print("[병기 — 판정에 쓰지 않음]")
    print("\n  구간별:")
    for H, lab in HORIZONS:
        rr = build(per, H)
        if len(rr) < 1000:
            print(f"    {lab:>4}: 매칭 {len(rr):,}건 — 부족"); continue
        bb, _, aa, _ = split(rr)
        print(f"    {lab:>4}: bid {bb.mean():+.4f}%  ask {aa.mean():+.4f}%  "
              f"차 {bb.mean()-aa.mean():+.4f}%p  (매칭 {len(rr):,})")

    print("\n  프린트 크기(ratio_to_median) 4분위별 [1시간]:")
    rt = np.array([x[4] for x in rows])
    qs = np.percentile(rt, [25, 50, 75])
    for i, (lo_q, hi_q) in enumerate(zip([-np.inf] + list(qs), list(qs) + [np.inf])):
        g = [x for x in rows if lo_q <= x[4] < hi_q]
        if len(g) < 500:
            continue
        bb, _, aa, _ = split(g)
        if not len(bb) or not len(aa):
            continue
        print(f"    Q{i+1} (ratio {lo_q:.0f}~{hi_q:.0f}): {len(g):>6,}건  "
              f"차 {bb.mean()-aa.mean():+.4f}%p")

    print("\n  코인 쏠림:")
    cc = {}
    for x in rows:
        cc[x[1]] = cc.get(x[1], 0) + 1
    top = sorted(cc.items(), key=lambda z: -z[1])[:5]
    for c, n in top:
        print(f"    {c:<10} {n:>7,}건 ({n/len(rows)*100:.1f}%)")
    nb = [x for x in rows if x[1] != "BTC"]
    if len(nb) > 1000:
        bb, _, aa, _ = split(nb)
        print(f"    BTC 제외 {len(nb):,}건 → 차 {bb.mean()-aa.mean():+.4f}%p")

    print("\n  2시간 레인지 내 위치(range_pos_2h) 상·하단 [1시간]:")
    for lab, sel in (("하단(<0.3)", lambda x: x[5] < 0.3), ("상단(>0.7)", lambda x: x[5] > 0.7)):
        g = [x for x in rows if not np.isnan(x[5]) and sel(x)]
        if len(g) < 500:
            print(f"    {lab}: {len(g)}건 — 부족"); continue
        bb, _, aa, _ = split(g)
        if not len(bb) or not len(aa):
            continue
        print(f"    {lab}: {len(g):>6,}건  차 {bb.mean()-aa.mean():+.4f}%p")

    print("\n  ※ 통과해도 주문 로직 아님 — 다음 단계는 모의 전략 사전등록 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
