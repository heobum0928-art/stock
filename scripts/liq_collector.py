"""
강제청산 수집기 — 바이낸스 선물 전종목 청산 스트림(!forceOrder@arr). **순수 수집. 주문 없음.**

목적: "큰 청산이 터진 뒤 가격이 과하게 밀렸다가 되돌아오는가"를 나중에 검정하기 위한 원자료.
지금은 아무 판단도 하지 않는다. 검정 기준은 표본이 쌓인 뒤 별도 사전등록으로 정한다.

기록 형식(data/liquidations.csv, 일 단위 롤링):
  ts_ms, symbol, side, price, qty, usdt, event_ms
  side=SELL 이면 롱 포지션이 강제청산된 것(가격을 아래로 민다),
  side=BUY 이면 숏이 청산된 것(가격을 위로 민다).

Run: .venv/Scripts/python.exe scripts/liq_collector.py
"""
import sys, os, csv, json, time, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import websockets

KST = timezone(timedelta(hours=9))
URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
OUT_DIR = ROOT / "data" / "liq"
LOG = ROOT / "logs" / "liq_collector.log"
STAT_EVERY = 1800          # 30분마다 통계 한 줄
FIELDS = ["ts_ms", "ts_kst", "symbol", "side", "price", "qty", "usdt"]


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} [LIQ] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def out_path(ms):
    d = datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / f"liq_{d}.csv"


def write_row(row):
    p = out_path(row["ts_ms"])
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


async def run():
    n_total, n_since, usdt_since, t_stat = 0, 0, 0.0, time.time()
    biggest = (0.0, "")
    while True:
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20,
                                          max_queue=1024) as ws:
                log(f"연결됨 — 전종목 강제청산 스트림 수집 시작 (기록 {OUT_DIR})")
                async for raw in ws:
                    try:
                        m = json.loads(raw)
                        o = m.get("o") or {}
                        price = float(o.get("ap") or o.get("p") or 0)
                        qty = float(o.get("z") or o.get("q") or 0)
                        if price <= 0 or qty <= 0:
                            continue
                        usdt = price * qty
                        ts = int(o.get("T") or m.get("E") or time.time() * 1000)
                        row = dict(ts_ms=ts,
                                   ts_kst=datetime.fromtimestamp(ts / 1000, KST).isoformat(),
                                   symbol=o.get("s", ""), side=o.get("S", ""),
                                   price=price, qty=qty, usdt=round(usdt, 2))
                        write_row(row)
                        n_total += 1; n_since += 1; usdt_since += usdt
                        if usdt > biggest[0]:
                            biggest = (usdt, row["symbol"])
                    except Exception as e:
                        log(f"파싱 오류: {e}")
                    if time.time() - t_stat >= STAT_EVERY:
                        log(f"30분 요약 — {n_since}건 / {usdt_since/1e6:.2f}M USDT "
                            f"| 최대 {biggest[0]/1e3:.0f}K {biggest[1]} | 누적 {n_total}건")
                        n_since, usdt_since, t_stat, biggest = 0, 0.0, time.time(), (0.0, "")
        except Exception as e:
            log(f"연결 끊김({e}) — 10초 후 재연결")
            await asyncio.sleep(10)


def main():
    log("=== 강제청산 수집기 시작 (순수 수집, 주문 없음) ===")
    asyncio.run(run())


if __name__ == "__main__":
    main()
