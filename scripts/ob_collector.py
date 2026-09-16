"""
호가창 수집기 — docs/PREREG_ORDERBOOK_COLLECT.md 사양 그대로. **순수 수집. 주문 없음.**

고정 6종목 + 급등 상위 4종목(1시간 갱신)의 20단계 호가를 5초마다 기록한다.
신호 생성·판단 없음. 판정 기준은 표본이 쌓인 뒤 별도 사전등록으로 정한다.

Run: .venv/Scripts/python.exe scripts/ob_collector.py
"""
import sys, os, csv, time, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

KST = timezone(timedelta(hours=9))
F = "https://fapi.binance.com"
OUT_DIR = ROOT / "data" / "ob"
LOG = ROOT / "logs" / "ob_collector.log"

# ── 사전등록 고정값 (PREREG_ORDERBOOK_COLLECT.md) ──
FIXED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"]
N_DYNAMIC = 4
DEPTH_LIMIT = 20
POLL_SEC = 5
REFRESH_H = 1
MIN_QVOL = 3_000_000
PUMP_LOOKBACK_H = 7
MIN_FREE_GB = 100
FIELDS = ["ts_ms", "ts_kst", "symbol", "mid", "spread_bp",
          "bid_usdt_20", "ask_usdt_20", "imb_20",
          "bid_usdt_5", "ask_usdt_5", "imb_5",
          "best_bid", "best_ask", "best_bid_qty", "best_ask_qty"]


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} [OB] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _get(path, **params):
    r = requests.get(F + path, params=params or None, timeout=15)
    if r.status_code == 429:
        raise RuntimeError("RATE_LIMIT_429")
    r.raise_for_status()
    return r.json()


def pick_dynamic():
    """24h 거래대금 300만 이상 중 7시간 급등률 상위 N — 봇이 실제로 잡는 종류."""
    try:
        tick = _get("/fapi/v1/ticker/24hr")
    except Exception as e:
        log(f"티커 조회 실패: {e}")
        return []
    cand = [d["symbol"] for d in tick
            if d["symbol"].endswith("USDT") and float(d["quoteVolume"]) >= MIN_QVOL
            and d["symbol"] not in FIXED]
    cand.sort(key=lambda s: -float(next(d["priceChangePercent"] for d in tick if d["symbol"] == s)))
    out = []
    for s in cand[:40]:                                   # 24h 상위 40개만 7h 계산(호출 절약)
        try:
            k = _get("/fapi/v1/klines", symbol=s, interval="1h", limit=PUMP_LOOKBACK_H + 1)
            if isinstance(k, list) and len(k) >= 2:
                out.append((s, (float(k[-1][4]) / float(k[0][1]) - 1) * 100))
        except Exception:
            pass
        time.sleep(0.05)
    out.sort(key=lambda x: -x[1])
    return [s for s, _ in out[:N_DYNAMIC]]


def snapshot(sym):
    d = _get("/fapi/v1/depth", symbol=sym, limit=DEPTH_LIMIT)
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    if not bids or not asks:
        return None
    b20 = sum(p * q for p, q in bids); a20 = sum(p * q for p, q in asks)
    b5 = sum(p * q for p, q in bids[:5]); a5 = sum(p * q for p, q in asks[:5])
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    ts = int(time.time() * 1000)
    return dict(ts_ms=ts, ts_kst=datetime.fromtimestamp(ts / 1000, KST).isoformat(),
                symbol=sym, mid=mid, spread_bp=round((ba - bb) / mid * 10000, 3),
                bid_usdt_20=round(b20, 2), ask_usdt_20=round(a20, 2),
                imb_20=round((b20 - a20) / (b20 + a20), 5) if b20 + a20 else 0,
                bid_usdt_5=round(b5, 2), ask_usdt_5=round(a5, 2),
                imb_5=round((b5 - a5) / (b5 + a5), 5) if b5 + a5 else 0,
                best_bid=bb, best_ask=ba,
                best_bid_qty=bids[0][1], best_ask_qty=asks[0][1])


def write_rows(rows):
    if not rows:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"ob_{datetime.now(KST).strftime('%Y-%m-%d')}.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    log(f"=== 호가창 수집 시작 (고정 {len(FIXED)} + 급등 {N_DYNAMIC}, {POLL_SEC}초, 주문 없음) ===")
    dyn, last_refresh = [], 0.0
    n_written, t_stat = 0, time.time()
    while True:
        try:
            if time.time() - last_refresh >= REFRESH_H * 3600:
                new_dyn = pick_dynamic()
                if new_dyn:
                    if new_dyn != dyn:
                        log(f"급등 종목 갱신: {[s[:-4] for s in new_dyn]}")
                    dyn, last_refresh = new_dyn, time.time()

            free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
            if free_gb < MIN_FREE_GB:
                log(f"★중단: 디스크 잔여 {free_gb:.0f}GB < {MIN_FREE_GB}GB (사전등록 5절)")
                return

            rows = []
            for s in FIXED + dyn:
                try:
                    r = snapshot(s)
                    if r:
                        rows.append(r)
                except RuntimeError as e:
                    if "429" in str(e):
                        log("★중단: 레이트리밋 429 — 실거래 봇 API 예산 보호 우선 (사전등록 5절)")
                        return
                except Exception:
                    pass
            write_rows(rows)
            n_written += len(rows)

            if time.time() - t_stat >= 1800:
                log(f"30분 요약 — {n_written}행 기록 | 대상 {len(FIXED)+len(dyn)}종목 | 디스크 여유 {free_gb:.0f}GB")
                n_written, t_stat = 0, time.time()
        except Exception as e:
            log(f"루프 오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
