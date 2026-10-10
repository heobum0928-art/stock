"""#56 업비트 원화마켓 신규 상장 1시간 뒤 바이낸스 선물 숏 — docs/PREREG_UPBIT_LISTING_SHORT.md 그대로 계산.

#55(scripts/bithumb_listing_short.py)와 규칙·비용·부트스트랩이 같다. 달라진 것은 상장 시각 출처(업비트)와
"주 표본 = 기초코인이 #55 표본에 없는 이벤트"라는 분할뿐. 주문 없음(가격 조회만).
"""
import sys, json, time, random, csv
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
sys.path.insert(0, str(ROOT / "scripts"))
import bithumb_listing_short as bls   # fget·sim·boot를 그대로 재사용(규칙 동일성 보장)

T0_CACHE = ROOT / "data" / "upbit_listing_t0.json"
SIM_CACHE = ROOT / "data" / "upbit_listing_short_cache.json"
OUT = ROOT / "data" / "upbit_listing_short_trades.csv"
B = "https://api.upbit.com/v1"
MIN_T0 = datetime(2021, 1, 1, tzinfo=timezone.utc)
MAX_T0 = datetime(2026, 10, 6, 23, 59, tzinfo=timezone.utc)
COST = bls.COST
random.seed(56); np.random.seed(56)
bls.random.seed(56)


def uget(path, **p):
    for i in range(8):
        try:
            r = requests.get(B + path, params=p, timeout=20)
            if r.status_code == 200:
                return r.json()
            time.sleep(0.4 * (i + 1))
        except Exception:
            time.sleep(0.4 * (i + 1))
    return None


def page_back(path, market, count, start_to=None):
    to, oldest, total = start_to, None, 0
    for _ in range(120):
        p = dict(market=market, count=count)
        if to:
            p["to"] = to
        r = uget(path, **p)
        if not r:
            break
        total += len(r)
        oldest = r[-1]
        if len(r) < count:
            break
        to = oldest["candle_date_time_utc"].replace("T", " ")   # 업비트 `to`는 UTC 기준 문자열
        time.sleep(0.12)
    return oldest, total


def listing_times():
    cache = json.loads(T0_CACHE.read_text(encoding="utf-8")) if T0_CACHE.exists() else {}
    mk = uget("/market/all")
    markets = sorted(x["market"] for x in mk if x["market"].startswith("KRW-"))
    print(f"업비트 KRW 마켓 {len(markets)}개", flush=True)
    for i, m in enumerate(markets):
        if m in cache:
            continue
        d, nd = page_back("/candles/days", m, 200)
        time.sleep(0.12)
        if not d:
            cache[m] = dict(status="일봉없음")
            continue
        day = d["candle_date_time_utc"][:10]
        nxt = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        mm, nm = page_back("/candles/minutes/1", m, 200, start_to=nxt)
        if not mm:
            cache[m] = dict(status="분봉없음", day=day)
            continue
        # 일봉이 API 한계(최대 120*200=24000일)에 걸리는 일은 없지만, 첫 분봉이 첫 날보다 이틀 이상 어긋나면 제외
        cache[m] = dict(status="ok", day=day, t0_utc=mm["candle_date_time_utc"], ndays=nd)
        if i % 30 == 0:
            T0_CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  상장시각 {i}/{len(markets)}", flush=True)
    T0_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def stat(net, T, day, label):
    n = len(net)
    if n == 0:
        print(f"[{label}] n=0"); return None
    lo, hi = bls.boot(list(net), day)
    med = np.median(T)
    h1 = net[T <= med]; h2 = net[T > med]
    print(f"[{label}] n={n}  평균(명목가, 비용·펀딩 후) {net.mean():+.3f}%  CI[{lo:+.3f}, {hi:+.3f}]  중앙 {np.median(net):+.2f}  승률 {np.mean(net>0)*100:.0f}%"
          f"  | 전반 n={len(h1)} {h1.mean() if len(h1) else float('nan'):+.3f}% / 후반 n={len(h2)} {h2.mean() if len(h2) else float('nan'):+.3f}%")
    return n, net.mean(), lo, (h1.mean() if len(h1) else None), (h2.mean() if len(h2) else None)


def main():
    t0s = listing_times()
    print("상장시각 상태:", dict(Counter(v["status"] for v in t0s.values())))
    ev, excl = [], Counter()
    for m, v in t0s.items():
        if v["status"] != "ok":
            excl[v["status"]] += 1
            continue
        t0 = datetime.strptime(v["t0_utc"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if t0 < MIN_T0:
            excl["2021이전"] += 1
            continue
        if t0 > MAX_T0:
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
    # #55 표본(빗썸 원화 상장 이벤트 중 선물 매칭 ok)의 기초코인
    bsim = json.loads(bls.SIM_CACHE.read_text(encoding="utf-8"))
    b55 = {m.split("-")[1] for m, r in bsim.items() if r.get("status") == "ok"}
    print(f"기간 내 업비트 상장 {len(uniq)}건, 제외: {dict(excl)} | #55 표본 기초코인 {len(b55)}개")
    cache = json.loads(SIM_CACHE.read_text(encoding="utf-8")) if SIM_CACHE.exists() else {}
    rows = []
    for i, (t0, m) in enumerate(uniq):
        r = dict(bls.sim(m, int(t0.timestamp() * 1000), cache))
        r.update(m=m, T=int(t0.timestamp() * 1000), overlap=m.split("-")[1] in b55)
        rows.append(r)
        if i % 25 == 0:
            SIM_CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  {i}/{len(uniq)}", flush=True)
        time.sleep(0.08)
    SIM_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    print("선물 매칭 상태:", dict(Counter(r["status"] for r in rows)))
    ok = [r for r in rows if r["status"] == "ok"]
    if not ok:
        print("표본 없음"); return
    net_all = np.array([r["raw_short"] - COST + r["fsum"] for r in ok])
    net2_all = np.array([r["raw_short"] - 2 * COST + r["fsum"] for r in ok])
    T_all = np.array([r["T"] for r in ok])
    day_all = np.array([datetime.fromtimestamp(r["T"] / 1000, timezone.utc).strftime("%Y-%m-%d") for r in ok])
    ov = np.array([r["overlap"] for r in ok])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["market", "t0_utc", "overlap_with_55", "net_short_pct", "stopped"])
        for r, x in zip(ok, net_all):
            w.writerow([r["m"], datetime.fromtimestamp(r["T"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M"),
                        r["overlap"], round(float(x), 3), r["stopped"]])
    print(f"선물 매칭 ok {len(ok)}건 (주 표본 {int((~ov).sum())} / 보조(#55와 같은 코인) {int(ov.sum())})")
    pm = ~ov
    res = stat(net_all[pm], T_all[pm], day_all[pm], "주 표본(판정)")
    print("  슬리피지 2배(0.24%) 평균:", f"{net2_all[pm].mean():+.3f}%" if pm.any() else "n/a",
          "| 손절 비율", f"{np.mean([r['stopped'] for r, p in zip(ok, pm) if p])*100:.0f}%" if pm.any() else "n/a",
          "| 펀딩 평균", f"{np.mean([r['fsum'] for r, p in zip(ok, pm) if p]):+.3f}%" if pm.any() else "n/a")
    stat(net_all[ov], T_all[ov], day_all[ov], "보조(보고만)")
    stat(net_all, T_all, day_all, "주+보조 합산(보고만)")
    yrs = {}
    for r, v, p in zip(ok, net_all, pm):
        if p:
            y = datetime.fromtimestamp(r["T"] / 1000, timezone.utc).year
            yrs.setdefault(y, []).append(v)
    print("주 표본 연도별:", {y: f"n={len(v)} {np.mean(v):+.2f}%" for y, v in sorted(yrs.items())})
    if res is None:
        print("판정: 표본 없음"); return
    n, mean, lo, h1, h2 = res
    if n < 60:
        print("판정: 판별 불가(n<60)")
    else:
        passed = mean > 0 and lo > 0 and h1 is not None and h2 is not None and h1 > 0 and h2 > 0
        print("판정:", "통과" if passed else "기각")


if __name__ == "__main__":
    main()
