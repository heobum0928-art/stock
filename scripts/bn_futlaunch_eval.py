"""#52 바이낸스 선물 신규 출시 공지 후 숏 — docs/PREREG_BN_FUTLAUNCH.md 그대로 계산.

규칙: 거래 시작 L의 60분 뒤 첫 5분봉 시가에 숏, 48h 뒤 종가 또는 손절(+5%, 갭이면 시가).
수익은 명목가 기준 %. 비용 왕복 0.12% + 실제 펀딩.
"""
import sys, re, json, time, random
from datetime import datetime, timezone
from pathlib import Path
import requests
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "bn_futlaunch_cache.json"
NOTICE = ROOT / "data" / "bn_futures_launch_notices.json"
F = "https://fapi.binance.com"
CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
STOP = 0.05
COST = 0.12          # 왕복 %, 명목가
HOLD_BARS = 576      # 48h / 5m
random.seed(52); np.random.seed(52)


def get(path, **p):
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


def fetch_notices():
    if NOTICE.exists():
        return json.loads(NOTICE.read_text(encoding="utf-8"))
    out = []
    for p in range(1, 80):
        r = requests.get(CMS, params=dict(type=1, catalogId=48, pageNo=p, pageSize=50), timeout=30).json()
        cs = r["data"]["catalogs"]
        a = cs[0]["articles"] if cs else []
        if not a:
            break
        out += a
        time.sleep(0.3)
    NOTICE.write_text(json.dumps(out), encoding="utf-8")
    return out


def events():
    seen, ev = set(), []
    for a in sorted(fetch_notices(), key=lambda x: x["releaseDate"]):
        t = a["title"]
        if "Perpetual" not in t or "Launch" not in t:
            continue
        syms = [s for s in re.findall(r"\b([A-Z0-9]{1,20}USDT)\b", t)]
        for s in dict.fromkeys(syms):
            if s in seen:
                continue
            seen.add(s)
            ev.append(dict(sym=s, T=a["releaseDate"], title=t))
    return ev


def sim(e, cache):
    k = cache.get(e["sym"])
    if k is not None:
        return k
    T = e["T"]
    res = dict(status="")
    first = get("/fapi/v1/klines", symbol=e["sym"], interval="1h", startTime=T - 6 * 3600 * 1000, limit=1)
    if not first:
        res["status"] = "조회불가"
        cache[e["sym"]] = res
        return res
    L = first[0][0]
    if L < T or L > T + 7 * 86400 * 1000:
        res["status"] = "L불일치"
        cache[e["sym"]] = res
        return res
    st = L + 3600 * 1000
    k5 = get("/fapi/v1/klines", symbol=e["sym"], interval="5m", startTime=st, limit=HOLD_BARS + 2)
    if not k5 or len(k5) < HOLD_BARS:
        res["status"] = "봉부족"
        res["n5"] = len(k5) if k5 else 0
        cache[e["sym"]] = res
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
    t_entry = k5[0][0]
    t_exit = k5[exit_i][6]
    fr = get("/fapi/v1/fundingRate", symbol=e["sym"], startTime=t_entry, endTime=t_exit, limit=1000) or []
    fsum = sum(float(x["fundingRate"]) for x in fr) * 100  # % (숏은 양(+)을 받는다)
    raw_short = (entry - exit_px) / entry * 100
    end48 = float(k5[-1][4])
    raw_long48 = (end48 - entry) / entry * 100
    res.update(status="ok", L=L, entry=entry, exit=exit_px, stopped=stopped, exit_i=exit_i,
               raw_short=raw_short, fsum=fsum, raw_long48=raw_long48, n_fund=len(fr))
    cache[e["sym"]] = res
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
    ev = events()
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    print(f"공지 이벤트(공지,심볼) {len(ev)}건")
    rows = []
    for i, e in enumerate(ev):
        r = sim(e, cache)
        if i % 25 == 0:
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  {i}/{len(ev)}", flush=True)
        r = dict(r)
        r.update(sym=e["sym"], T=e["T"])
        rows.append(r)
        time.sleep(0.08)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")

    from collections import Counter
    print("상태:", dict(Counter(r["status"] for r in rows)))
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
    print(f"n={n} (조회불가 {sum(r['status']=='조회불가' for r in rows)}, 전체 {len(rows)})")
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
