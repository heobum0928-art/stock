"""#55 빗썸 원화마켓 신규 상장 1시간 뒤 바이낸스 선물 숏 — docs/PREREG_BITHUMB_LISTING_SHORT.md 그대로 계산.

규칙: 상장 시각 T0(첫 1분봉, UTC)의 60분 뒤 첫 5분봉 시가에 숏, 48h 뒤 종가 또는 손절(+5%, 갭이면 시가).
수익은 명목가 기준 %. 비용 왕복 0.12% + 실제 펀딩. 주문 없음(가격 조회만).
"""
import sys, json, time, random
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
T0_CACHE = ROOT / "data" / "bithumb_listing_t0.json"
SIM_CACHE = ROOT / "data" / "bithumb_listing_short_cache.json"
B = "https://api.bithumb.com/v1"
F = "https://fapi.binance.com"
STOP = 0.05
COST = 0.12
HOLD_BARS = 576
MIN_T0 = datetime(2021, 1, 1, tzinfo=timezone.utc)
MAX_T0 = datetime(2026, 10, 6, 23, 59, tzinfo=timezone.utc)
random.seed(55); np.random.seed(55)


def bget(path, **p):
    for i in range(5):
        try:
            r = requests.get(B + path, params=p, timeout=20)
            if r.status_code == 200:
                return r.json()
            time.sleep(0.5 * (i + 1))
        except Exception:
            time.sleep(0.5 * (i + 1))
    return None


def fget(path, **p):
    for i in range(4):
        try:
            r = requests.get(F + path, params=p, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def page_back(path, market, count, start_to=None):
    """가장 오래된 봉까지 거슬러 올라가 (가장 오래된 봉 dict, 총 봉 수) 반환."""
    to, oldest, total = start_to, None, 0
    for _ in range(80):
        p = dict(market=market, count=count)
        if to:
            p["to"] = to
        r = bget(path, **p)
        if not r:
            break
        total += len(r)
        oldest = r[-1]
        if len(r) < count:
            break
        to = oldest["candle_date_time_kst"].replace("T", " ")
        time.sleep(0.03)
    return oldest, total


def listing_times():
    cache = json.loads(T0_CACHE.read_text(encoding="utf-8")) if T0_CACHE.exists() else {}
    mk = bget("/market/all")
    markets = sorted(x["market"] for x in mk if x["market"].startswith("KRW-"))
    for i, m in enumerate(markets):
        if m in cache:
            continue
        d, nd = page_back("/candles/days", m, 200)
        if not d:
            cache[m] = dict(status="일봉없음")
            continue
        day = d["candle_date_time_kst"][:10]
        nxt = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        mm, nm = page_back("/candles/minutes/1", m, 200, start_to=nxt)
        if not mm:
            cache[m] = dict(status="분봉없음", day=day)
            continue
        cache[m] = dict(status="ok", day=day, t0_utc=mm["candle_date_time_utc"])
        if i % 40 == 0:
            T0_CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  상장시각 {i}/{len(markets)}", flush=True)
    T0_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def find_symbol(base, entry_ms, cache_sym):
    for s in (base + "USDT", "1000" + base + "USDT"):
        k = fget("/fapi/v1/klines", symbol=s, interval="5m", startTime=entry_ms, limit=1)
        if k and k[0][0] <= entry_ms + 10 * 60 * 1000:
            return s
        time.sleep(0.05)
    return None


def sim(m, t0_ms, cache):
    if m in cache:
        return cache[m]
    base = m.split("-")[1]
    res = dict(status="")
    entry_ms = ((t0_ms + 3600 * 1000 + 299999) // 300000) * 300000
    s = find_symbol(base, entry_ms, None)
    if not s:
        res["status"] = "선물없음"
        cache[m] = res
        return res
    k5 = fget("/fapi/v1/klines", symbol=s, interval="5m", startTime=entry_ms, limit=HOLD_BARS + 2)
    if not k5 or len(k5) < HOLD_BARS:
        res["status"] = "봉부족"
        cache[m] = res
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
    fr = fget("/fapi/v1/fundingRate", symbol=s, startTime=k5[0][0], endTime=k5[exit_i][6], limit=1000) or []
    fsum = sum(float(x["fundingRate"]) for x in fr) * 100
    raw_short = (entry - exit_px) / entry * 100
    raw_long48 = (float(k5[-1][4]) - entry) / entry * 100
    res.update(status="ok", sym=s, entry=entry, exit=exit_px, stopped=stopped, raw_short=raw_short,
               fsum=fsum, raw_long48=raw_long48)
    cache[m] = res
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


def main():
    t0s = listing_times()
    from collections import Counter
    print("상장시각 상태:", dict(Counter(v["status"] for v in t0s.values())))
    ev, excl = [], Counter()
    # ★ 2026-10-09: 전방 모드(날짜 인자)는 48h가 지난 상장까지 계속 포함해야 하므로 상한을 현재 기준으로 갱신.
    #   고정 MAX_T0(10-06)이면 새 상장이 영원히 표본에 안 들어온다. 기존 재현(인자 없음)은 그대로.
    max_t0 = (datetime.now(timezone.utc) - timedelta(hours=50)) if len(sys.argv) > 1 else MAX_T0
    for m, v in t0s.items():
        if v["status"] != "ok":
            excl[v["status"]] += 1
            continue
        t0 = datetime.strptime(v["t0_utc"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if t0 < MIN_T0:
            excl["2021이전"] += 1
            continue
        if t0 > max_t0:
            excl["최근(48h 미확보)"] += 1
            continue
        ev.append((t0, m))
    ev.sort()
    seen, uniq = set(), []
    for t0, m in ev:
        b = m.split("-")[1]
        if b in seen:
            continue
        seen.add(b)
        uniq.append((t0, m))
    if len(sys.argv) > 1:   # 전방 검증용: python ... 2026-10-09 → 그 날짜(UTC) 이후 상장만
        since = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        uniq = [(t, m) for t, m in uniq if t > since]
    print(f"기간 내 상장 {len(uniq)}건, 제외: {dict(excl)}")
    cache = json.loads(SIM_CACHE.read_text(encoding="utf-8")) if SIM_CACHE.exists() else {}
    rows = []
    for i, (t0, m) in enumerate(uniq):
        r = dict(sim(m, int(t0.timestamp() * 1000), cache))
        r.update(m=m, T=int(t0.timestamp() * 1000))
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
    if len(sys.argv) > 1:   # 전방 기록 저장(갱신 시 전체 재작성)
        import csv
        with open(ROOT / "data" / "bithumb_listing_forward.csv", "w", newline="", encoding="utf-8") as _f:
            _w = csv.writer(_f); _w.writerow(["market", "t0_utc", "net_short_pct", "stopped"])
            for _r, _x in zip(ok, net):
                _w.writerow([_r["m"], datetime.fromtimestamp(_r["T"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M"),
                             round(float(_x), 3), _r["stopped"]])
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
    yrs = {}
    for r, v in zip(ok, net):
        y = datetime.fromtimestamp(r["T"] / 1000, timezone.utc).year
        yrs.setdefault(y, []).append(v)
    print("연도별:", {y: f"n={len(v)} {np.mean(v):+.2f}%" for y, v in sorted(yrs.items())})
    verdict = n >= 60 and net.mean() > 0 and lo > 0 and h1.mean() > 0 and h2.mean() > 0
    print("판정:", "통과" if verdict else "기각")


if __name__ == "__main__":
    main()
