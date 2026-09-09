"""
그림자함대 보조 진단 — 평일/주말 분리 성적 (판정 근거 아님, 기록용).

2026-09-05 작성. PREREG_FLEET_V6V7.md / PREREG_HOLD24.md 원칙: "국면 분해는 보고하되 판정에
쓰지 않는다". 이 스크립트는 fleet_v6v7_eval.py(판정 전 수정 금지)와 분리해 둔다.
배경: 2026-09-05 실거래 115건에서 주말이 좋아 보였으나 8/15-16 한 주말이 전부였음
(그 주말 제외 시 주말 합 -77 USDT). 표본이 쌓여도 같은 방향이면 그때 가설로 올린다.

Run: .venv/Scripts/python.exe scripts/fleet_diag_split.py
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def split(df, tcol, pcol, label):
    t = pd.to_datetime(df[tcol], utc=True).dt.tz_convert("Asia/Seoul")
    wk = t.dt.dayofweek.map(lambda d: "주말" if d >= 5 else "평일")
    g = df.groupby(wk).agg(n=(pcol, "count"), 승률=(pcol, lambda s: round((s > 0).mean() * 100)),
                          건당=(pcol, "mean"), 최악=(pcol, "min")).round(2)
    print(f"\n[{label}]"); print(g.to_string())
    # 최대 기여 주말 하나 제외 시
    w = df[wk == "주말"].copy()
    if len(w):
        w["wkend"] = t[wk == "주말"].dt.to_period("W").astype(str)
        per = w.groupby("wkend")[pcol].agg(["count", "sum", "mean"]).round(1)
        print("  주말별:"); print(per.to_string())
        print(f"  주말 전체 평균 {w[pcol].mean():+.2f} | 최고 주말 제외 평균 "
              f"{w[~w.wkend.eq(per['sum'].idxmax())][pcol].mean() if len(per) > 1 else float('nan'):+.2f}")


def main():
    led = pd.concat([pd.read_csv(ROOT / "data" / "margin_short_ledger.csv"),
                     pd.read_csv(ROOT / "data" / "margin_short_wide_ledger.csv")])
    split(led, "entry_time", "net_pnl_pct_margin", "실거래 원장 (증거금 기준 순%, 진입 요일)")
    f = pd.read_csv(ROOT / "data" / "shadow_trades.csv")
    for v in ("V1_notrail", "V6_timestop", "V7_fundexit"):
        d = f[f.variant == v]
        if len(d):
            split(d, "entry_time", "net_pnl_pct_margin", f"그림자함대 {v}")
    print("\n※ 판정 근거 아님. 국면 분해는 보고만 한다(PREREG_HOLD24 5항 4).")


if __name__ == "__main__":
    main()
