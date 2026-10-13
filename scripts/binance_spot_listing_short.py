"""#58 바이낸스 현물 신규 상장 1시간 뒤, 이미 선물이 있는 코인 숏 — docs/PREREG_BN_SPOT_LISTING_SHORT.md 그대로 계산.

규칙: 현물 첫 1분봉(UTC) T0의 60분 뒤 첫 5분봉 시가에 숏, 48h 뒤 종가 또는 손절(+5%, 갭이면 시가).
수익은 명목가 기준 %. 비용 왕복 0.12% + 실제 펀딩. 주문 없음(가격 조회만).
사용: python scripts/binance_spot_listing_short.py            (전체 재현)
      python scripts/binance_spot_listing_short.py 2026-10-13  (그 날짜 이후 상장만 — 전방 기록)
"""
import sys, json, time, random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter
import requests
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
T0_CACHE = ROOT / "data" / "bn_spot_listing_t0.json"
SIM_CACHE = ROOT / "data" / "bn_spot_listing_short_cache.json"
S = "https://api.binance.com"
F = "https://fapi.binance.com"
STOP = 0.05
COST = 0.12
HOLD_BARS = 576
MIN_T0 = datetime(2021, 1, 1, tzinfo=timezone.utc)
EXCLUDE = {"USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "USDE", "USD1", "USDS", "PYUSD", "RLUSD",
           "EUR", "AEUR", "EURI", "XUSD", "BFUSD", "WBTC", "WBETH", "BETH", "BNSOL"}
random.seed(58); np.random.seed(58)


def get(base, path, **p):
    for i in range(4):
        try:
            r = requests.get(base + path, params=p, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def spot_t0s():
    cache = json.loads(T0_CACHE.read_text(encoding="utf-8")) if T0_CACHE.exists() else {}
    info = get(S, "/api/v3/exchangeInfo")
    mk = [(x["symbol"], x["baseAsset"]) for x in info["symbols"]
          if x["quoteAsset"] == "USDT" and x["status"] == "TRADING" and x.get("isSpotTradingAllowed")]
    for i, (sym, base) in enumerate(mk):
        if sym in cache:
            continue
        k = get(S, "/api/v3/klines", symbol=sym, interval="1m", startTime=0, limit=1)
        cache[sym] = dict(base=base, t0=int(k[0][0])) if k else dict(base=base, t0=None)
        if i % 50 == 0:
            T0_CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  현물 T0 {i}/{len(mk)}", flush=True)
        time.sleep(0.06)
    T0_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def find_symbol(base, entry_ms):
    for s in (base + "USDT", "1000" + base + "USDT", "1000000" + base + "USDT"):
        k = get(F, "/fapi/v1/klines", symbol=s, interval="5m", startTime=entry_ms, limit=1)
        if k and k[0][0] <= entry_ms + 10 * 60 * 1000:
            return s
        time.sleep(0.05)
    return None


def sim(key, base, t0_ms, cache):
    if key in cache:
        return cache[key]
    res = dict(status="")
    entry_ms = ((t0_ms + 3600 * 1000 + 299999) // 300000) * 300000
    s = find_symbol(base, entry_ms)
    if not s:
        res["status"] = "선물없음"
        cache[key] = res
        return res
    k5 = get(F, "/fapi/v1/klines", symbol=s, interval="5m", startTime=entry_ms, limit=HOLD_BARS + 2)
    if not k5 or len(k5) < HOLD_BARS:
        res["status"] = "봉부족"
        cache[key] = res
        return res
    k5 = k5[:HOLD_BARS]
    entry = float(k5[0][1])
    stop_lvl = entry * (1 + STOP)
    exit_px, exit_i, stopped = float(k5[-1][4]), HOLD_BARS - 1, False
    for i, b in enumerate(k5):
        hi, op = float(b[2]), float(b[1])
        if hi >= stop_lvl:
            exit_px, exit_i, stopped = max(stop_lvl, op), i, True
            break
    fr = get(F, "/fapi/v1/fundingRate", symbol=s, startTime=k5[0][0], endTime=k5[exit_i][6], limit=1000) or []
    fsum = sum(float(x["fundingRate"]) for x in fr) * 100
    raw_short = (entry - exit_px) / entry * 100
    raw_long48 = (float(k5[-1][4]) - entry) / entry * 100
    res.update(status="ok", sym=s, entry=entry, exit=exit_px, stopped=stopped, raw_short=raw_short,
               fsum=fsum, raw_long48=raw_long48)
    cache[key] = res
    return res


def boot(vals, clusters, n=5000):
    cl = {}
    for v, c in zip(vals, clusters):
        cl.setdefault(c, []).append(v)
    keys = list(cl)
    m = []
    for _ in range(n):
        pick = [keys[random.randrange(len(keys))] for _ in keys]
        xs = [x for k in pick for x in cl[k]]
        m.append(np.mean(xs))
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def bithumb_bases():
    """#55 표본에 들어간(빗썸 원화에 상장된) 기초코인 — 독립성 진단용(판정에 쓰지 않음)."""
    p = ROOT / "data" / "bithumb_listing_t0.json"
    if not p.exists():
        return set()
    return {m.split("-")[1] for m, v in json.loads(p.read_text(encoding="utf-8")).items()
            if v.get("status") == "ok"}


def main():
    t0s = spot_t0s()
    max_t0 = datetime.now(timezone.utc) - timedelta(hours=50)
    ev, excl = [], Counter()
    for sym, v in t0s.items():
        if v["t0"] is None:
            excl["봉없음"] += 1
            continue
        if v["base"] in EXCLUDE:
            excl["고정제외(스테이블·래핑)"] += 1
            continue
        t0 = datetime.fromtimestamp(v["t0"] / 1000, timezone.utc)
        if t0 < MIN_T0:
            excl["2021이전"] += 1
            continue
        if t0 > max_t0:
            excl["최근(48h 미확보)"] += 1
            continue
        ev.append((t0, sym, v["base"]))
    ev.sort()
    seen, uniq = set(), []
    for t0, sym, base in ev:
        if base in seen:
            continue
        seen.add(base)
        uniq.append((t0, sym, base))
    if len(sys.argv) > 1:
        since = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        uniq = [x for x in uniq if x[0] > since]
    print(f"기간 내 현물 상장 {len(uniq)}건, 제외: {dict(excl)}")
    cache = json.loads(SIM_CACHE.read_text(encoding="utf-8")) if SIM_CACHE.exists() else {}
    rows = []
    for i, (t0, sym, base) in enumerate(uniq):
        r = dict(sim(sym, base, int(t0.timestamp() * 1000), cache))
        r.update(m=sym, base=base, T=int(t0.timestamp() * 1000))
        rows.append(r)
        if i % 25 == 0:
            SIM_CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  {i}/{len(uniq)}", flush=True)
        time.sleep(0.08)
    SIM_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    print("선물 매칭 상태:", dict(Counter(r["status"] for r in rows)))
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(ok)
    if n == 0:
        print("표본 없음"); return
    net = np.array([r["raw_short"] - COST + r["fsum"] for r in ok])
    net2 = np.array([r["raw_short"] - 2 * COST + r["fsum"] for r in ok])
    day = [datetime.fromtimestamp(r["T"] / 1000, timezone.utc).strftime("%Y-%m-%d") for r in ok]
    lo, hi = boot(list(net), day)
    Ts = np.array([r["T"] for r in ok]); med = np.median(Ts)
    h1 = net[Ts <= med]; h2 = net[Ts > med]
    print(f"n={n} (후보 {len(uniq)}, 비율 {n/len(uniq)*100:.0f}%)")
    print(f"숏 건당 평균 순수익(명목가, 비용·펀딩 후) {net.mean():+.3f}%  CI[{lo:+.3f}, {hi:+.3f}]  중앙 {np.median(net):+.3f}  승률 {np.mean(net>0)*100:.0f}%")
    print(f"전반 n={len(h1)} 평균 {h1.mean():+.3f}% / 후반 n={len(h2)} 평균 {h2.mean():+.3f}%")
    print(f"손절 비율 {np.mean([r['stopped'] for r in ok])*100:.0f}% | 펀딩 평균 {np.mean([r['fsum'] for r in ok]):+.3f}% | 최악 {net.min():+.1f}% 최고 {net.max():+.1f}%")
    print(f"슬리피지 2배(왕복 0.24%) 평균 {net2.mean():+.3f}%")
    lg = np.array([r["raw_long48"] - COST - r["fsum"] for r in ok])
    print(f"(참고) 롱 48h 무손절 평균 {lg.mean():+.3f}%")
    s = np.sort(net)[::-1]
    if n > 10:
        print(f"(참고) 상위 5건 제외 평균 {s[5:].mean():+.3f}% / 상위 10건 제외 {s[10:].mean():+.3f}%")
    yrs = {}
    for r, v in zip(ok, net):
        y = datetime.fromtimestamp(r["T"] / 1000, timezone.utc).year
        yrs.setdefault(y, []).append(v)
    print("연도별:", {y: f"n={len(v)} {np.mean(v):+.2f}%" for y, v in sorted(yrs.items())})
    bb = bithumb_bases()
    ov = np.array([r["base"] in bb for r in ok])
    if bb:
        print(f"(독립성 진단) #55 표본과 겹치는 코인 {ov.sum()}/{n} ({ov.mean()*100:.0f}%) | 겹침 평균 {net[ov].mean() if ov.any() else float('nan'):+.3f}% | "
              f"겹치지 않음 n={int((~ov).sum())} 평균 {net[~ov].mean() if (~ov).any() else float('nan'):+.3f}%")
    verdict = n >= 60 and net.mean() > 0 and lo > 0 and h1.mean() > 0 and h2.mean() > 0
    print("판정:", ("통과" if verdict else ("판별 불가(n<60)" if n < 60 else "기각")))
    if len(sys.argv) > 1:
        import csv
        with open(ROOT / "data" / "bn_spot_listing_forward.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["spot_symbol", "t0_utc", "net_short_pct", "stopped"])
            for r, x in zip(ok, net):
                w.writerow([r["m"], datetime.fromtimestamp(r["T"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M"),
                            round(float(x), 3), r["stopped"]])


if __name__ == "__main__":
    main()
