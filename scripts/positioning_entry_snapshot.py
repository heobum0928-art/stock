"""[수집 전용] 봇이 진입한 종목의 '진입 시점 쏠림'을 찍어둔다 — 주문·판단 없음, GET만.

왜 필요한가 (2026-09-03):
  펀딩 필터 검정에서 "펀딩 방향이 아니라 한쪽으로 쏠렸다는 사실 자체가 변수"라는 결과가
  나왔다(방향 무관 대칭 필터 +5.18%p > 방향성 규칙 +4.86%p). 그런데 쏠림을 **직접 재는**
  데이터는 바이낸스가 30일치만 준다 — 과거 진입 건에 소급 적용할 수 없다.
  그래서 지금부터 진입할 때마다 그 순간의 쏠림을 남긴다.

이 스크립트는 봇을 수정하지 않는다. 봇의 *_pos.json을 **읽기만** 한다.
positioning_logger.py(시장 전체 6종목 상시적재)와 역할이 다르다 — 이건 진입 종목 전용.

한계(미리 명시): 진입이 월 9~11건이라 이 데이터만으로 판정에 이르려면 18개월 이상 걸린다.
판정용이 아니라 **"우리가 들어간 자리가 실제로 몰린 자리였나"를 사실로 확인**하기 위한 것이다.

실행: .venv/Scripts/python.exe scripts/positioning_entry_snapshot.py   (1회 = 1회 점검)
저장: data/positioning_entries.csv  (진입 1건당 시간별 여러 행, (symbol,entry_ts)로 중복 방지)
"""
import os, csv, json, time, requests, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://fapi.binance.com"
OUT  = os.path.join(ROOT, "data", "positioning_entries.csv")
# 읽을 봇 상태 파일 (봇은 수정하지 않는다)
POS_FILES = {
    "mshort":      os.path.join(ROOT, "data", "margin_short_pos.json"),
    "mshort_wide": os.path.join(ROOT, "data", "margin_short_wide_pos.json"),
}
COLS = ["symbol", "bot", "entry_ts", "entry_iso", "entry_price", "margin", "venue",
        "snap_ts", "hours_to_entry", "close", "global_ls", "global_long",
        "top_pos_ls", "top_acct_ls", "taker_bs", "oi", "oi_value", "funding_rate"]

S = requests.Session()

def _get(ep, sym, params=None):
    p = {"symbol": sym, "period": "1h", "limit": 30}
    if params: p.update(params)
    try:
        r = S.get(BASE + ep, params=p, timeout=20)
        j = r.json() if r.status_code == 200 else []
        return {int(x["timestamp"]): x for x in j} if isinstance(j, list) else {}
    except Exception:
        return {}

def _funding(sym):
    try:
        r = S.get(BASE + "/fapi/v1/fundingRate", params={"symbol": sym, "limit": 20}, timeout=20)
        j = r.json() if r.status_code == 200 else []
        return sorted((int(x["fundingTime"]), float(x["fundingRate"])) for x in j) if isinstance(j, list) else []
    except Exception:
        return []

def _fund_at(fr, ts):
    """ts 직전에 정산된 펀딩률 (미래 정보 없음)."""
    v = ""
    for ft, r in fr:
        if ft <= ts: v = r
        else: break
    return v

def open_positions():
    out = []
    for bot, p in POS_FILES.items():
        if not os.path.exists(p): continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict): continue
        for sym, v in d.items():
            if not isinstance(v, dict): continue
            ts = v.get("entry_ts")
            if not ts: continue
            out.append((sym, bot, int(float(ts) * (1000 if float(ts) < 1e12 else 1)), v))
    return out

def already(sym, ets):
    if not os.path.exists(OUT): return set()
    with open(OUT, newline="", encoding="utf-8") as f:
        return {(r["symbol"], r["entry_ts"]) for r in csv.DictReader(f)}

def snapshot(sym, bot, ets, v):
    g  = _get("/futures/data/globalLongShortAccountRatio", sym)
    tp = _get("/futures/data/topLongShortPositionRatio", sym)
    ta = _get("/futures/data/topLongShortAccountRatio", sym)
    tk = _get("/futures/data/takerlongshortRatio", sym)
    oi = _get("/futures/data/openInterestHist", sym)
    fr = _funding(sym)
    if not g: return []
    try:
        k = S.get(BASE + "/fapi/v1/klines",
                  params={"symbol": sym, "interval": "1h", "limit": 40}, timeout=20).json()
        px = {int(x[0]): float(x[4]) for x in k}
    except Exception:
        px = {}
    iso = dt.datetime.fromtimestamp(ets / 1000, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for ts in sorted(g):
        gg = g[ts]
        rows.append({
            "symbol": sym, "bot": bot, "entry_ts": ets, "entry_iso": iso,
            "entry_price": v.get("entry_price", ""), "margin": v.get("margin", ""),
            "venue": v.get("venue", ""),
            "snap_ts": ts, "hours_to_entry": round((ts - ets) / 3600000, 2),
            "close": px.get(ts, ""),
            "global_ls":   gg.get("longShortRatio", ""),
            "global_long": gg.get("longAccount", ""),
            "top_pos_ls":  tp.get(ts, {}).get("longShortRatio", ""),
            "top_acct_ls": ta.get(ts, {}).get("longShortRatio", ""),
            "taker_bs":    tk.get(ts, {}).get("buySellRatio", ""),
            "oi":          oi.get(ts, {}).get("sumOpenInterest", ""),
            "oi_value":    oi.get(ts, {}).get("sumOpenInterestValue", ""),
            "funding_rate": _fund_at(fr, ts),
        })
    return rows

if __name__ == "__main__":
    pos = open_positions()
    if not pos:
        print("열린 포지션 없음 — 할 일 없음"); raise SystemExit(0)
    seen = already(None, None)
    new = []
    for sym, bot, ets, v in pos:
        if (sym, str(ets)) in seen:
            print(f"  {sym:12s} 이미 기록됨 (진입 {ets})"); continue
        r = snapshot(sym, bot, ets, v)
        if r:
            new += r
            print(f"  {sym:12s} {bot:12s} +{len(r)}행  (진입 {r[0]['entry_iso']})")
        else:
            print(f"  {sym:12s} 데이터 없음 — 건너뜀")
        time.sleep(0.4)
    if new:
        ex = os.path.exists(OUT)
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            if not ex: w.writeheader()
            w.writerows(new)
    print(f"신규 {len(new)}행 → {OUT}")
