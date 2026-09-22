"""PREREG_COINPAN_BUZZ.md 실행 — 코인판 게시글 언급(화제성) 후 가격 반응.

Run: .venv/Scripts/python.exe scripts/coinpan_buzz_eval.py
"""
import csv, re, os, sys, time, json
from datetime import datetime, timezone, timedelta
import numpy as np
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
SRC = "data/coinpan_posts.csv"
CACHE = "data/_coinpan_buzz_kl.json"
COST = 0.12
ENTRY_DELAY = 600          # 10분
COOLDOWN = 86400           # 24시간
HS = [(60, "1시간"), (240, "4시간"), (1440, "24시간")]
MAIN_H = 60
MIN_N = 30
SEED, BOOT = 20260922, 4000
SLEEP = 0.3

BLOCK = {"ON","IT","ME","MY","OK","SO","NO","TV","US","UK","ID","PC","AI","CEO","ETF","SEC",
         "NFT","DEX","CEX","KYC","AML","GDP","FED","IMF","ICO","IPO","TOP","ALL","NEW","WHY",
         "HOW","GO","IN","OUT","UP","DOWN","CAN","WILL","ARE","WAS","THE","AND","FOR","NOW",
         "GET","SET","BUY","SELL","WIN","LOSE","RUN","JOB","KRW","USD","USDT","PDF","URL",
         "CPU","GPU","RAM","FAQ","VIP","LOL"}

_cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def klines(sym, t0ms, t1ms):
    key = f"{sym}|{t0ms}|{t1ms}"
    if key in _cache:
        return _cache[key]
    rows, cur = [], t0ms
    for _ in range(6):
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}"
               f"&interval=5m&startTime={cur}&endTime={t1ms}&limit=1500")
        for a in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    d = json.load(r)
                break
            except Exception:
                if a == 3:
                    _cache[key] = None
                    return None
                time.sleep(2 * (a + 1))
        if not d:
            break
        rows += [[int(k[0]), float(k[4])] for k in d]
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 300_000
        time.sleep(SLEEP)
    _cache[key] = rows
    time.sleep(SLEEP)
    return rows


def extract(title):
    toks = set(re.findall(r"(?<![A-Za-z])[A-Z]{2,6}(?![A-Za-z])", title))
    return toks - BLOCK


def main():
    syms = {os.path.basename(p)[:-4] for p in __import__("glob").glob("research/m5bt/pq/*.npz")}
    syms = {s[:-4] for s in syms}  # strip USDT
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    print("[코인판 화제성] 사전등록 docs/PREREG_COINPAN_BUZZ.md (커밋 53b15b9)")
    print(f"게시글 {len(rows):,}건, 기간 {rows[0]['first_seen'][:10]} ~ {rows[-1]['first_seen'][:10]}\n")

    events, matched = [], 0
    for r in rows:
        toks = extract(r["title"]) & syms
        if not toks:
            continue
        try:
            t = datetime.fromisoformat(r["first_seen"]).timestamp()
        except Exception:
            continue
        matched += 1
        for tk in toks:
            events.append(dict(coin=tk, t=t, board=r["board"], title=r["title"],
                               views=int(r["views"] or 0)))
    print(f"티커 매칭 게시글 {matched:,}건 / 코인-이벤트 {len(events):,}건 (중복 코인 포함)")

    events.sort(key=lambda e: e["t"])
    last_seen = {}
    kept = []
    for e in events:
        k = e["coin"]
        if k in last_seen and e["t"] - last_seen[k] < COOLDOWN:
            continue
        last_seen[k] = e["t"]
        kept.append(e)
    print(f"24시간 쿨다운 적용 후 {len(kept)}건\n")

    out = []
    for e in kept:
        sym = e["coin"] + "USDT"
        t0 = int(e["t"] * 1000)
        ent_ms = t0 + ENTRY_DELAY * 1000
        kl = klines(sym, t0 - 300_000, t0 + 1440 * 60_000 + 300_000)
        if not kl:
            continue
        entb = [k for k in kl if k[0] <= ent_ms]
        if not entb:
            continue
        p_in = entb[-1][1]
        if p_in <= 0:
            continue
        rec = dict(e, p_in=p_in)
        ok = False
        for m, _ in HS:
            tgt = ent_ms + m * 60_000
            fut = [k for k in kl if k[0] >= tgt]
            rec[m] = (fut[0][1] / p_in - 1) * 100 - COST if fut else None
            if m == MAIN_H and rec[m] is not None:
                ok = True
        if ok:
            out.append(rec)
    try:
        json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
    except Exception:
        pass

    print(f"바이낸스 선물 매칭 성공 {len(out)}건 (선물 미상장/데이터없음 {len(kept)-len(out)}건)\n")
    print("=" * 78)
    for r in sorted(out, key=lambda z: z["t"])[:40]:
        ts = datetime.fromtimestamp(r["t"], KST).strftime("%m-%d %H:%M")
        h1 = r[MAIN_H]
        print(f"  {r['coin']:<8}{ts:<14}[{r['board']:<9}] {h1:+7.2f}%  {r['title'][:34]}")
    if len(out) > 40:
        print(f"  ... 외 {len(out)-40}건")

    if len(out) < MIN_N:
        print(f"\n  ▶ C1: 유효 이벤트 {len(out)}건 < {MIN_N} — **표본 부족, 보류**")
        print("  (참고, 판정에 쓰지 않음)")
    x = np.array([r[MAIN_H] for r in out])
    print(f"\n주 구간 1시간: n={len(x)}  평균 {x.mean():+.3f}%  중앙 {np.median(x):+.3f}%  "
          f"양수비율 {(x>0).mean()*100:.0f}%")
    rng = np.random.default_rng(SEED)
    bs = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(BOOT)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"95% CI [{lo:+.3f}, {hi:+.3f}]  (이벤트 재추출 {BOOT}회, 시드 {SEED}) — 26일뿐이라 "
          f"날짜블록 대신 이벤트 단위(한계)")

    if len(out) < MIN_N:
        verdict = "표본 부족 — 보류 (C1)"
    elif abs(x.mean()) >= COST * 5 and not (lo <= 0 <= hi):
        verdict = "쓸 만한 신호(방향 무관) — 전방 모의만 (C2)"
    else:
        verdict = "판별 불가 (C3)"
    print(f"\n  ▶ 판정: {verdict}")

    print("\n" + "=" * 78 + "\n[병기 — 판정에 쓰지 않음]")
    for lab in ("pnl", "futures", "free", "coin_info"):
        g = np.array([r[MAIN_H] for r in out if r["board"] == lab])
        if len(g):
            print(f"  board={lab:<10} n={len(g):>4}  평균 {g.mean():+.3f}%  양수 {(g>0).mean()*100:.0f}%")
    for m, lab in HS:
        g = np.array([r[m] for r in out if r[m] is not None])
        if len(g):
            print(f"  {lab:>4}: n={len(g):>4}  평균 {g.mean():+.3f}%  양수 {(g>0).mean()*100:.0f}%")
    from collections import Counter
    top = Counter(r["coin"] for r in out).most_common(5)
    tot = len(out)
    print(f"  상위 코인 쏠림: " + ", ".join(f"{c} {n}({n/tot*100:.0f}%)" for c, n in top))
    print("\n  ※ 실거래·주문 로직 아님. 26일 표본으로 확정하지 않는다 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
