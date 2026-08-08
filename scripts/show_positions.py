"""[조회] 보유 포지션 한눈에 보기 — 종목/방향/수익률/순익 간단 표시."""
import sys, json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def price(sym):
    r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": sym}, timeout=5)
    return float(r.json()["price"])


def main():
    rows = []

    ms = ROOT / "data" / "margin_short_pos.json"
    if ms.exists():
        for sym, p in json.loads(ms.read_text(encoding="utf-8")).items():
            cur = price(sym)
            pnl_pct = (1 - cur / p["entry_price"]) * 100
            pnl_usdt = p["margin"] * 2 * (pnl_pct / 100)
            rows.append((p["coin"], "숏", pnl_pct, pnl_usdt))

    ml = ROOT / "data" / "margin_manual_long_pos.json"
    if ml.exists():
        for coin, p in json.loads(ml.read_text(encoding="utf-8")).items():
            cur = price(coin + "USDT")
            pnl_pct = (cur / p["entry_price"] - 1) * 100
            pnl_usdt = p["qty"] * (cur - p["entry_price"])
            rows.append((coin, "롱", pnl_pct, pnl_usdt))

    if not rows:
        print("보유 포지션 없음")
        return

    print(f"{'종목':<8}{'방향':<6}{'수익률':>10}{'순익(USDT)':>14}")
    for coin, direction, pct, usdt in rows:
        print(f"{coin:<8}{direction:<6}{pct:>+9.1f}%{usdt:>+13.2f}")


if __name__ == "__main__":
    main()
