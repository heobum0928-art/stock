"""PREREG_UPBIT_LISTING2.md 실행 — T+30초 실제 체결 가능 가격 기준 재측정(1분봉).

Run: .venv/Scripts/python.exe scripts/upbit_listing_eval2.py
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
CACHE = "data/_upbit_listing_1m.json"
ENTRY_DELAY = 30            # 초
SLIP = 0.10                 # 진입 슬리피지 %(명목)
FEE = 0.12                  # 왕복 수수료 %(명목)
COST = SLIP + FEE
MAIN_H = 60
HS = [(5, "5분"), (15, "15분"), (60, "1시간"), (240, "4시간")]
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
               f"&interval=1m&startTime={cur}&endTime={t1ms}&limit=1500")
        for a in range(4):
            try:
                with urllib.request.urlopen(url, timeout=25) as r:
                    d = json.load(r)
                break
            except Exception:
                if a == 3:
                    _cache[key] = None
                    return None
                time.sleep(3 * (a + 1))
        if not d:
            break
        rows += [[int(k[0]), float(k[1]), float(k[4])] for k in d]
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 60_000
        time.sleep(SLEEP)
    _cache[key] = rows
    time.sleep(SLEEP)
    return rows


def load_events():
    out = []
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
                continue
            T = det - timedelta(seconds=delay)
            tks = [t for t in re.findall(r"\(([A-Z0-9]{2,12})\)", r["title"])
                   if t not in ("KRW", "BTC", "USDT")]
            for tk in dict.fromkeys(tks):
                out.append(dict(coin=tk, T=T, gid=r["notice_id"], krw=("KRW" in r["title"])))
    return out


def main():
    ev = load_events()
    print("[업비트 상장 2차 — 실제 체결가 기준] 사전등록 docs/PREREG_UPBIT_LISTING2.md (커밋 fa6114c)")
    print(f"진입 = 공지 +{ENTRY_DELAY}초가 속한 1분봉 종가 | 비용 {COST:.2f}%(슬리피지 {SLIP}+수수료 {FEE})\n")

    rows = []
    for e in ev:
        sym = e["coin"] + "USDT"
        t0 = int(e["T"].timestamp() * 1000)
        ent_ms = t0 + ENTRY_DELAY * 1000
        kl = klines(sym, t0 - 600_000, t0 + 300 * 60_000)
        if not kl:
            continue
        pre = [k for k in kl if k[0] + 60_000 <= t0]        # 공지 전 완전히 끝난 봉
        entb = [k for k in kl if k[0] <= ent_ms < k[0] + 60_000]
        if not pre or not entb:
            continue
        p_pre = pre[-1][2]
        p_in = entb[0][2]
        if p_pre <= 0 or p_in <= 0:
            continue
        rec = dict(coin=e["coin"], T=e["T"], gid=e["gid"], krw=e["krw"],
                   missed=(p_in / p_pre - 1) * 100, p_in=p_in)
        ok = False
        for m, _ in HS:
            tgt = entb[0][0] + m * 60_000
            fut = [k for k in kl if k[0] >= tgt]
            rec[m] = (fut[0][2] / p_in - 1) * 100 - COST if fut else None
            if m == MAIN_H and rec[m] is not None:
                ok = True
        if ok:
            rows.append(rec)

    try:
        json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
    except Exception:
        pass

    print(f"유효 {len(rows)}건\n" + "=" * 86)
    print(f"{'코인':<10}{'공지시각':<14}{'놓친점프':>9}" + "".join(f"{l:>10}" for _, l in HS))
    for r in sorted(rows, key=lambda z: z["T"]):
        s = f"{r['coin']:<10}{r['T'].strftime('%m-%d %H:%M'):<14}{r['missed']:>+8.2f}%"
        for m, _ in HS:
            s += f"{r[m]:>+9.2f}%" if r[m] is not None else f"{'-':>10}"
        print(s)

    print("\n" + "=" * 86)
    print(f"{'구간':>6} {'건수':>5} {'평균':>9} {'중앙':>9} {'양수':>7} {'최대':>9} {'최소':>9}")
    for m, lab in HS:
        x = np.array([r[m] for r in rows if r[m] is not None])
        if len(x):
            print(f"{lab:>6} {len(x):>5} {x.mean():>+8.2f}% {np.median(x):>+8.2f}% "
                  f"{(x>0).mean()*100:>6.0f}% {x.max():>+8.2f}% {x.min():>+8.2f}%")

    ms_ = np.array([r["missed"] for r in rows])
    print(f"\n공지~진입 사이 놓친 점프: 평균 {ms_.mean():+.2f}%  중앙 {np.median(ms_):+.2f}%  최대 {ms_.max():+.2f}%")

    x = np.array([r[MAIN_H] for r in rows if r[MAIN_H] is not None])
    g = np.array([r["gid"] for r in rows if r[MAIN_H] is not None])
    ug = np.unique(g)
    rng = np.random.default_rng(SEED)
    bs = np.empty(BOOT)
    for k in range(BOOT):
        sel = np.concatenate([np.nonzero(g == ug[p])[0] for p in rng.integers(0, len(ug), len(ug))])
        bs[k] = x[sel].mean()
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"\n주 구간 1시간: 순수익 평균 {x.mean():+.2f}%  95% CI [{lo:+.2f}, {hi:+.2f}]  "
          f"(공지 {len(ug)}건 단위 재추출 {BOOT}회, 시드 {SEED})")
    print(f"1차(5분봉 시가 기준) 1시간 평균 +8.85% → 2차 {x.mean():+.2f}%  "
          f"차이 {x.mean()-8.85:+.2f}%p (과대평가분)")

    if x.mean() <= 0:
        v = "기각 (V4)"
    elif lo <= 0:
        v = "판별 불가 (V3)"
    elif x.mean() >= 2.0:
        v = ("쓸 만한 신호 — 전방 모의 진행 (V1)" if len(x) >= 15
             else "표본 부족이나 V5 예외 충족 → **보류(전방 모의 착수 가능)**")
    else:
        v = "존재하나 얇음 — 전방 모의만 (V2)" if len(x) >= 15 else "표본 부족 — 보류 (V5)"
    print(f"\n  ▶ 판정: {v}")
    print("  ※ 실거래 없음. 다음 단계는 전방 모의뿐 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
