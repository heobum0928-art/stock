"""PREREG_CONCURRENCY_CAP.md 실행 — 동시 보유 상한 K의 계좌 수익률 효과.

Run: .venv/Scripts/python.exe scripts/concurrency_cap_eval.py
"""
import csv, sys
from datetime import datetime
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LEDGERS = [("원본", "data/margin_short_ledger.csv"), ("완화", "data/margin_short_wide_ledger.csv")]
M = 100.0          # 건당 증거금
C = 5 * M          # 계좌 자본 — 전 조건 동일 (사전등록 2항)
CAPS = [None, 5, 3, 2]
MAIN = 3
SEED, BOOT, BLOCK_DAYS = 20260918, 4000, 7


def load():
    out = []
    for eng, path in LEDGERS:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    pct = float(r["net_pnl_pct_margin"])
                    tin = datetime.fromisoformat(r["entry_time"])
                    tout = datetime.fromisoformat(r["exit_time"])
                except Exception:
                    continue
                if pct < -100:
                    continue
                out.append(dict(eng=eng, sym=r["symbol"], tin=tin, tout=tout, pct=pct))
    out.sort(key=lambda x: x["tin"])
    return out


def replay(trades, cap):
    """상한 cap으로 재생. 체결된 거래 리스트와 건너뛴 거래 리스트를 돌려준다."""
    taken, skipped, open_until = [], [], []
    for t in trades:
        open_until = [x for x in open_until if x > t["tin"]]
        if cap is not None and len(open_until) >= cap:
            skipped.append(t)
            continue
        open_until.append(t["tout"])
        taken.append(t)
    return taken, skipped


def acct_ret(taken):
    """계좌 수익률 % = 총손익 / C. 손익 = Σ(pct/100 × M)."""
    return sum(t["pct"] / 100.0 * M for t in taken) / C * 100.0


def mdd(taken):
    """청산 시각 순 누적 손익의 최대 낙폭(계좌 대비 %)."""
    if not taken:
        return 0.0
    s = sorted(taken, key=lambda t: t["tout"])
    eq = np.cumsum([t["pct"] / 100.0 * M for t in s]) / C * 100.0
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))
    return float((np.concatenate([[0.0], eq]) - peak).min())


def avg_conc(taken):
    ev = []
    for t in taken:
        ev.append((t["tin"], 1)); ev.append((t["tout"], -1))
    ev.sort()
    c, prev, area, tot = 0, None, 0.0, 0.0
    for tm, d in ev:
        if prev is not None:
            h = (tm - prev).total_seconds() / 3600
            area += c * h; tot += h
        c += d; prev = tm
    return area / tot if tot else 0.0


def block_stats(trades, cap, seed=SEED, iters=BOOT):
    """7일 블록 재추출. 블록 안에서 상한 규칙을 다시 재생한다."""
    days = np.array([int(t["tin"].timestamp() // 86400) for t in trades])
    b = (days - days.min()) // BLOCK_DAYS
    ub = np.unique(b)
    groups = [[trades[i] for i in np.nonzero(b == u)[0]] for u in ub]
    rng = np.random.default_rng(seed)
    out = np.empty(iters)
    for k in range(iters):
        vals = []
        for p in rng.integers(0, len(groups), len(groups)):
            g = groups[p]
            vals.append(acct_ret(replay(g, cap)[0]))
        out[k] = np.mean(vals)
    return out, len(groups)


def main():
    tr = load()
    print("[동시 보유 상한] 사전등록 docs/PREREG_CONCURRENCY_CAP.md (커밋 590bfe4)")
    print(f"청산 완료 숏 거래 {len(tr)}건 (이상치 제외), 건당 증거금 {M:.0f}, 계좌 자본 {C:.0f} 고정\n")
    if len(tr) < 100:
        print("  ▶ C5: 표본 부족 — 판정 보류"); return

    print("=" * 76)
    print(f"{'상한':>6} {'체결':>5} {'건너뜀':>6} {'계좌수익률':>10} {'MDD':>9} {'평균동시':>8} {'건너뛴건 평균':>12}")
    res = {}
    for cap in CAPS:
        tk, sk = replay(tr, cap)
        r = acct_ret(tk)
        res[cap] = (tk, sk, r)
        sm = np.mean([t["pct"] for t in sk]) if sk else float("nan")
        lab = "없음" if cap is None else f"K={cap}"
        print(f"{lab:>6} {len(tk):>5} {len(sk):>6} {r:>+9.1f}% {mdd(tk):>+8.1f}% "
              f"{avg_conc(tk):>8.2f} {sm:>+11.2f}%")

    # ===== 주 판정 =====
    print("\n" + "=" * 76)
    base_b, nb = block_stats(tr, None)
    print(f"7일 블록 {nb}개, {BOOT}회, 시드 {SEED}\n")
    verdict = None
    for cap in [c for c in CAPS if c is not None]:
        cb, _ = block_stats(tr, cap)
        d = cb - base_b
        lo, hi = np.percentile(d, [2.5, 97.5])
        se = d.std(ddof=1)
        m = 2.802 * se
        pt = res[cap][2] - res[None][2]
        tag = "주 판정" if cap == MAIN else "강건성 병기(승격 금지)"
        print(f"  K={cap}  [{tag}]")
        print(f"    계좌수익률 차 (실측) {pt:+.1f}%p")
        print(f"    블록 평균 차 {d.mean():+.2f}%p   95% CI [{lo:+.2f}, {hi:+.2f}]   MDE {m:.2f}%p")
        sk = res[cap][1]
        for eng in ("원본", "완화"):
            n = sum(1 for t in sk if t["eng"] == eng)
            tot = sum(1 for t in tr if t["eng"] == eng)
            print(f"    └ {eng}봇 건너뜀 {n}/{tot}건 ({n/tot*100:.0f}%)")
        if cap == MAIN:
            if d.mean() > 0 and lo > 0:
                verdict = "동시 보유 상한 효과 확인 (C1)"
            elif d.mean() > 0 and abs(d.mean()) >= m:
                verdict = "유망 — 전방 재확인 (C2)"
            elif abs(d.mean()) < m:
                verdict = "판별 불가 (C3)"
            else:
                verdict = "기각 — 상한 두지 않는 게 낫다 (C4)"
        print()

    # 최대기여 단일 날짜
    tk = res[MAIN][0]
    ds = {}
    for t in tk:
        k = int(t["tout"].timestamp() // 86400)
        ds[k] = ds.get(k, 0) + t["pct"] / 100.0 * M
    tot = sum(abs(v) for v in ds.values())
    if tot:
        print(f"  K={MAIN} 최대기여 단일 청산일 비중 {max(abs(v) for v in ds.values())/tot*100:.1f}%")

    print("\n" + "=" * 76)
    print(f"  ▶ 판정 (주 비교 K={MAIN}): {verdict}")
    print("  ※ 통과해도 실거래 자동 반영 없음 — 봇 변경은 사용자 결정 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
