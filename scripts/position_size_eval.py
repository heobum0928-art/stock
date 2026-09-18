"""PREREG_POSITION_SIZE.md 실행 — 증거금 비중 f의 복리 성장·파산 곡선.

Run: .venv/Scripts/python.exe scripts/position_size_eval.py
"""
import csv, sys
from datetime import datetime
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LEDGERS = ["data/margin_short_ledger.csv", "data/margin_short_wide_ledger.csv"]
W0 = 1000.0
RUIN = 0.20            # W0의 20% 미만 → 파산
FS = [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30]
SEED, BOOT, BLOCK_DAYS = 20260918, 4000, 7


def load():
    out = []
    for path in LEDGERS:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    pct = float(r["net_pnl_pct_margin"])
                    tin = datetime.fromisoformat(r["entry_time"]).timestamp()
                    tout = datetime.fromisoformat(r["exit_time"]).timestamp()
                except Exception:
                    continue
                if pct < -100:
                    continue
                out.append((tin, tout, pct))
    out.sort()
    return out


def sim(trades, f, track=False):
    """진입 순 재생, 청산 시각에 반영. 복리."""
    eq = W0
    deployed = 0.0
    events = []          # (시각, 종류, ...) 진입/청산을 시간순 처리
    for tin, tout, pct in trades:
        events.append((tin, 0, tout, pct))
    events.sort()
    pending = []         # (tout, margin, pct)
    curve = [(0.0, eq)]
    peak, mdd = eq, 0.0
    n_taken = 0
    ruined = False
    for tin, _, tout, pct in events:
        # 이 진입 전에 끝난 청산들 먼저 반영
        pending.sort()
        while pending and pending[0][0] <= tin:
            to, mg, pc = pending.pop(0)
            eq += mg * pc / 100.0
            deployed -= mg
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            if track:
                curve.append((to, eq))
            if eq < W0 * RUIN:
                ruined = True
                break
        if ruined:
            break
        free = max(eq - deployed, 0.0)
        mg = min(eq * f, free)
        if mg <= 1e-9:
            continue
        deployed += mg
        pending.append((tout, mg, pct))
        n_taken += 1
    if not ruined:
        for to, mg, pc in sorted(pending):
            eq += mg * pc / 100.0
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            if track:
                curve.append((to, eq))
            if eq < W0 * RUIN:
                ruined = True
                break
    return dict(final=eq / W0, mdd=mdd * 100, ruined=ruined, n=n_taken)


def main():
    tr = load()
    print("[포지션 크기 곡선] 사전등록 docs/PREREG_POSITION_SIZE.md (커밋 31f87c2)")
    print(f"숏 {len(tr)}건, 시작자산 {W0:.0f}, 파산선 {RUIN*100:.0f}%\n")

    print("=" * 72)
    print(f"{'f':>6} {'최종배수':>9} {'MDD':>9} {'체결':>5}  {'파산':>5}")
    real = {}
    for f in FS:
        r = sim(tr, f)
        real[f] = r
        print(f"{f*100:>5.0f}% {r['final']:>8.2f}x {r['mdd']:>+8.1f}% {r['n']:>5}  "
              f"{'파산' if r['ruined'] else '  -':>5}")

    # ===== 부트스트랩 =====
    days = np.array([int(t[0] // 86400) for t in tr])
    b = (days - days.min()) // BLOCK_DAYS
    ub = np.unique(b)
    groups = [[tr[i] for i in np.nonzero(b == u)[0]] for u in ub]
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(groups), (BOOT, len(groups)))

    print(f"\n{'='*72}")
    print(f"7일 블록 {len(groups)}개, {BOOT}회, 시드 {SEED}")
    print(f"{'f':>6} {'중앙 최종배수':>13} {'5%':>8} {'95%':>9} {'파산확률':>8}")
    med, best_per_iter = {}, np.zeros(BOOT, dtype=int)
    allfin = {}
    for f in FS:
        fin = np.empty(BOOT)
        ruin = 0
        for k in range(BOOT):
            seq = []
            off = 0.0
            for p in picks[k]:
                for tin, tout, pct in groups[p]:
                    seq.append((tin + off, tout + off, pct))
                off += BLOCK_DAYS * 86400
            seq.sort()
            r = sim(seq, f)
            fin[k] = r["final"]
            ruin += r["ruined"]
        allfin[f] = fin
        med[f] = float(np.median(fin))
        lo, hi = np.percentile(fin, [5, 95])
        print(f"{f*100:>5.0f}% {med[f]:>12.2f}x {lo:>7.2f}x {hi:>8.2f}x {ruin/BOOT*100:>7.1f}%")

    FA = np.array(FS)
    stack = np.vstack([allfin[f] for f in FS])      # (len(FS), BOOT)
    best_per_iter = FA[np.argmax(stack, axis=0)]
    fstar = max(FS, key=lambda f: med[f])
    f5, f95 = np.percentile(best_per_iter, [5, 95])
    ruinp = {f: float(np.mean([1 if x < RUIN else 0 for x in allfin[f]])) for f in FS}

    print(f"\n{'='*72}")
    print(f"  f* (부트스트랩 중앙값 최대) = {fstar*100:.0f}%")
    print(f"  f*의 부트스트랩 산포: 5% {f5*100:.0f}% ~ 95% {f95*100:.0f}%")
    wide = (f95 - f5) > (FA[1] - FA[0]) * 1.5
    if wide:
        print("  ▶ 산포가 격자 폭보다 넓다 — **f*는 이 표본으로 결정되지 않는다.**")
        print("    단일 숫자를 권하지 않는다 (사전등록 4항).")
    print(f"  권장 보고값 (하프켈리) = f*/2 = {fstar*50:.1f}%")
    unusable = [f for f in FS if ruinp[f] > 0.05]
    if unusable:
        print(f"  ▶ 파산확률 5% 초과로 **쓸 수 없음**: " +
              ", ".join(f"{f*100:.0f}%" for f in unusable))

    print(f"\n  [현재 운영값 위치] 선물 지갑 약 1,455 USDT 기준")
    for name, m in (("원본봇 증거금 120", 120.0), ("완화봇 증거금 80", 80.0)):
        f = m / 1455.0
        print(f"    {name} → f ≈ {f*100:.1f}%")
    print("\n  ※ 합격 기준 없음. 증거금 변경은 사용자 결정 (CLAUDE.md 6항).")
    print("  ※ 173건은 2개월 한 국면이다. 다음 국면에 같은 f가 최적이라는 보장은 없다.")


if __name__ == "__main__":
    main()
