"""[수집 전용] 포지션 쏠림 데이터 적재 — 주문·판단 없음. 읽기만 한다.

바이낸스는 롱숏비·미결제약정 이력을 최대 30일만 준다. 3.5년 백테스트가 불가능하므로
지금부터 직접 쌓는다. 목표: 6개월 뒤 검정 가능한 표본 확보.

수집 대상 (모두 공개 데이터):
  globalLongShortAccountRatio  전체 계정 롱숏비  ~ 개미 포지션
  topLongShortPositionRatio    상위 트레이더    ~ 큰손 포지션
  takerlongshortRatio          테이커 매수/매도  ~ 능동 주문 방향
  openInterestHist             미결제약정        ~ 전체 포지션 규모
  + 같은 시각 종가 (사후 수익률 계산용)

실행: .venv/Scripts/python.exe scripts/positioning_logger.py
     (1회 실행 = 1회 적재. 스케줄러로 1시간마다 돌리면 된다.)
저장: data/positioning/{SYMBOL}.csv  (append, 중복 timestamp는 건너뜀)
"""
import os, sys, csv, time, requests, datetime as dt

BASE = "https://fapi.binance.com"
OUT  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "positioning")
PERIOD = "1h"
# BTC/ETH는 시장 대표, 나머지는 마진숏이 실제로 다루는 알트 성격
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"]
COLS = ["timestamp", "utc", "close", "global_ls", "global_long",
        "top_pos_ls", "top_acct_ls", "taker_bs", "oi", "oi_value"]

S = requests.Session()

def _get(ep, sym, limit=30):
    try:
        r = S.get(BASE + ep, params={"symbol": sym, "period": PERIOD, "limit": limit}, timeout=20)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def _idx(rows, key="timestamp"):
    return {int(x[key]): x for x in rows} if isinstance(rows, list) else {}

def collect(sym):
    g  = _idx(_get("/futures/data/globalLongShortAccountRatio", sym))
    tp = _idx(_get("/futures/data/topLongShortPositionRatio", sym))
    ta = _idx(_get("/futures/data/topLongShortAccountRatio", sym))
    tk = _idx(_get("/futures/data/takerlongshortRatio", sym))
    oi = _idx(_get("/futures/data/openInterestHist", sym))
    if not g:
        return 0
    try:
        k = S.get(BASE + "/fapi/v1/klines",
                  params={"symbol": sym, "interval": "1h", "limit": 60}, timeout=20).json()
        px = {int(x[0]): float(x[4]) for x in k}
    except Exception:
        px = {}

    p = os.path.join(OUT, f"{sym}.csv")
    seen = set()
    if os.path.exists(p):
        with open(p, newline="", encoding="utf-8") as f:
            seen = {r["timestamp"] for r in csv.DictReader(f)}
    new = []
    for ts in sorted(g):
        if str(ts) in seen:
            continue
        gg = g[ts]
        new.append({
            "timestamp": ts,
            "utc": dt.datetime.fromtimestamp(ts / 1000, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "close": px.get(ts, ""),
            "global_ls":   gg.get("longShortRatio", ""),
            "global_long": gg.get("longAccount", ""),
            "top_pos_ls":  tp.get(ts, {}).get("longShortRatio", ""),
            "top_acct_ls": ta.get(ts, {}).get("longShortRatio", ""),
            "taker_bs":    tk.get(ts, {}).get("buySellRatio", ""),
            "oi":          oi.get(ts, {}).get("sumOpenInterest", ""),
            "oi_value":    oi.get(ts, {}).get("sumOpenInterestValue", ""),
        })
    if not new:
        return 0
    exists = os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not exists:
            w.writeheader()
        w.writerows(new)
    return len(new)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    tot = 0
    for s in SYMS:
        n = collect(s)
        tot += n
        print(f"  {s:10s} +{n}건")
        time.sleep(0.3)
    print(f"신규 {tot}건 적재 → {OUT}")
