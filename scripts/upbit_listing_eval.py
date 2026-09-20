"""PREREG_UPBIT_LISTING.md 실행 — 업비트 상장 공지 후 바이낸스 선물 가격 반응.

Run: .venv/Scripts/python.exe scripts/upbit_listing_eval.py
"""
import csv, re, sys, time, json, os
from datetime import datetime, timezone, timedelta
import numpy as np
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
SRC = "data/upbit_notice_events.csv"
BRE = "data/breadth_events.csv"
CACHE = "data/_upbit_listing_kl.json"
COST = 0.12
MAIN_H = 60
HS = [(5, "5분"), (15, "15분"), (60, "1시간"), (240, "4시간"), (1440, "24시간")]
MAX_DELAY = 600
SEED, BOOT = 20260920, 4000
SLEEP = 0.35

_cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def klines(sym, t0ms, t1ms):
    key = f"{sym}|{t0ms}|{t1ms}"
    if key in _cache:
        return _cache[key]
    rows, cur = [], t0ms
    for _ in range(10):
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}"
               f"&interval=5m&startTime={cur}&endTime={t1ms}&limit=1500")
        for a in range(4):
            try:
                with urllib.request.urlopen(url, timeout=25) as r:
                    d = json.load(r)
                break
            except Exception as e:
                if a == 3:
                    _cache[key] = None
                    return None
                time.sleep(3 * (a + 1))
        if not d:
            break
        rows += [[int(k[0]), float(k[1]), float(k[4])] for k in d]
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 300_000
        time.sleep(SLEEP)
    _cache[key] = rows
    time.sleep(SLEEP)
    return rows


def load_events():
    out, skipped_delay = [], 0
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["is_listing"] != "True":
                continue
            try:
                det = datetime.fromisoformat(r["detected_at"]).replace(tzinfo=KST)
                delay = float(r["delay_sec"] or 0)
            except Exception:
                continue
            if delay > MAX_DELAY:
                skipped_delay += 1
                continue
            T = det - timedelta(seconds=delay)
            tickers = re.findall(r"\(([A-Z0-9]{2,12})\)", r["title"])
            tickers = [t for t in tickers if t not in ("KRW", "BTC", "USDT")]
            for tk in dict.fromkeys(tickers):
                out.append(dict(coin=tk, T=T, title=r["title"],
                                krw=("KRW" in r["title"]), gid=r["notice_id"]))
    return out, skipped_delay


def breadth_at(ts):
    if not hasattr(breadth_at, "rows"):
        rows = []
        with open(BRE, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append((datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
                                 .replace(tzinfo=KST).timestamp(), float(r["breadth_6h"])))
                except Exception:
                    pass
        rows.sort()
        breadth_at.rows = rows
    a = np.array([x[0] for x in breadth_at.rows])
    i = np.searchsorted(a, ts, side="right") - 1
    if i < 0 or ts - a[i] > 1800:
        return None
    return breadth_at.rows[i][1]


def main():
    ev, skipped_delay = load_events()
    print("[업비트 상장 공지 반응] 사전등록 docs/PREREG_UPBIT_LISTING.md (커밋 035c211)")
    print(f"상장 공지에서 추출한 코인 {len(ev)}건 (지연 600초 초과로 제외 {skipped_delay}건)\n")

    rows, no_fut = [], []
    for e in ev:
        sym = e["coin"] + "USDT"
        t0 = int(e["T"].timestamp() * 1000)
        kl = klines(sym, t0 - 3600_000, t0 + 1440 * 60_000 + 600_000)
        if not kl:
            no_fut.append(e["coin"]); continue
        base = [k for k in kl if k[0] <= t0]
        if not base or not any(k[0] < t0 - 300_000 for k in kl):
            no_fut.append(e["coin"]); continue
        bar = base[-1]
        p0 = bar[1]                       # 그 봉의 시가
        if p0 <= 0:
            no_fut.append(e["coin"]); continue
        rec = dict(coin=e["coin"], T=e["T"], krw=e["krw"], gid=e["gid"],
                   breadth=breadth_at(e["T"].timestamp()))
        ok = True
        for m, lab in HS:
            tgt = t0 + m * 60_000
            fut = [k for k in kl if k[0] >= tgt]
            if not fut:
                rec[m] = None
                if m == MAIN_H:
                    ok = False
                continue
            rec[m] = (fut[0][2] / p0 - 1) * 100
        if ok:
            rows.append(rec)
    try:
        json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
    except Exception:
        pass

    print(f"유효 {len(rows)}건 / 선물 미상장·데이터 없음 {len(no_fut)}건 {sorted(set(no_fut))}\n")
    if len(rows) < 15:
        print(f"  ▶ U5: 유효 건수 {len(rows)} < 15 — **표본 부족, 판정 보류**")
    print("=" * 96)
    print(f"{'코인':<10}{'공지시각(KST)':<18}{'KRW':<5}" + "".join(f"{l:>9}" for _, l in HS) + f"{'폭':>7}")
    for r in sorted(rows, key=lambda z: z["T"]):
        s = f"{r['coin']:<10}{r['T'].strftime('%m-%d %H:%M'):<18}{'Y' if r['krw'] else '-':<5}"
        for m, _ in HS:
            v = r[m]
            s += f"{v:>+8.2f}%" if v is not None else f"{'-':>9}"
        s += f"{r['breadth']:>7.2f}" if r["breadth"] is not None else f"{'-':>7}"
        print(s)

    print("\n" + "=" * 96)
    print(f"{'구간':>6} {'건수':>5} {'평균':>9} {'중앙':>9} {'양수비율':>9} {'최대':>9} {'최소':>9}")
    for m, lab in HS:
        x = np.array([r[m] for r in rows if r[m] is not None])
        if not len(x):
            continue
        print(f"{lab:>6} {len(x):>5} {x.mean():>+8.2f}% {np.median(x):>+8.2f}% "
              f"{(x>0).mean()*100:>8.0f}% {x.max():>+8.2f}% {x.min():>+8.2f}%")

    x = np.array([r[MAIN_H] for r in rows if r[MAIN_H] is not None])
    gids = np.array([r["gid"] for r in rows if r[MAIN_H] is not None])
    ug = np.unique(gids)
    rng = np.random.default_rng(SEED)
    ms = np.empty(BOOT)
    for k in range(BOOT):
        pick = rng.integers(0, len(ug), len(ug))
        sel = np.concatenate([np.nonzero(gids == ug[p])[0] for p in pick])
        ms[k] = x[sel].mean()
    lo, hi = np.percentile(ms, [2.5, 97.5])

    print(f"\n주 구간 1시간: 평균 {x.mean():+.2f}%  95% CI [{lo:+.2f}, {hi:+.2f}]  "
          f"(공지 {len(ug)}건 단위 재추출 {BOOT}회, 시드 {SEED})")
    print(f"왕복 비용 {COST}% / U1 문턱 {COST*5:.2f}%")
    if len(rows) < 15:
        v = "표본 부족 — 판정 보류 (U5)"
    elif x.mean() < 0:
        v = "기각 (U4)"
    elif lo <= 0:
        v = "판별 불가 (U3)"
    elif x.mean() >= COST * 5 and lo > COST:
        v = "쓸 만한 신호 (U1)"
    elif x.mean() >= COST and lo > 0:
        v = "존재하나 얇음 (U2)"
    else:
        v = "판별 불가 (U3)"
    print(f"\n  ▶ 판정: {v}")

    for lab, sel in (("KRW 마켓 포함", lambda r: r["krw"]), ("KRW 미포함", lambda r: not r["krw"])):
        y = np.array([r[MAIN_H] for r in rows if sel(r) and r[MAIN_H] is not None])
        if len(y):
            print(f"  [병기] {lab}: {len(y)}건 평균 {y.mean():+.2f}%")
    print("\n  ※ 통과해도 주문 로직 아님 — 다음 단계는 전방 모의 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
