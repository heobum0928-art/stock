"""[알림] 보유 포지션 현황을 텔레그램으로 전송 — show_positions.py와 동일 포맷.
1시간마다 작업 스케줄러(CoinbaseTelegramStatus)로 실행."""
import sys, json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bithumb import notify


def price(sym):
    r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": sym}, timeout=5)
    return float(r.json()["price"])


def build_text():
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
        return "[포지션현황] 보유 포지션 없음"

    lines = ["[포지션현황]", "<pre>"]
    lines.append(f"{'종목':<7}{'방향':<4}{'수익률':>8}{'순익':>9}")
    total = 0.0
    for coin, direction, pct, usdt in rows:
        lines.append(f"{coin:<7}{direction:<4}{pct:>+7.1f}%{usdt:>+9.2f}")
        total += usdt
    lines.append(f"{'합계':<15}{total:>+9.2f}")
    lines.append("</pre>")
    return "\n".join(lines)


def main():
    text = build_text()
    notify.send(text, force=True)
    print(text)


if __name__ == "__main__":
    main()
