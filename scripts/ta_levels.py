"""
기술적 레벨 계산기 — 눌림목·지지·저항. 2026-09-12 사용자 요청.

**계산기다. 추천이 아니다.** 아래 값은 전부 가격 데이터에서 기계적으로 나온다.

## 무엇을 계산하나
- **저항선**: 최근 스윙 고점(좌우 N봉보다 높은 봉의 고가)을 가격대로 묶어 터치 횟수 순
- **지지선**: 최근 스윙 저점(좌우 N봉보다 낮은 봉의 저가)을 같은 방식으로
- **거래량 집중대(VPOC)**: 거래대금이 가장 많이 쌓인 가격 구간 — 실질 지지/저항
- **눌림목 여부**: 상승 추세(현재가 > MA25 > MA99) 중 최근 고점 대비 되돌림
- **피보나치 되돌림**: 최근 스윙 저점~고점의 38.2% / 50% / 61.8%

Run: .venv/Scripts/python.exe scripts/ta_levels.py SYMBOL [SYMBOL2 ...]
     .venv/Scripts/python.exe scripts/ta_levels.py --scan     ← 눌림목 종목 찾기
"""
import sys, os, time, argparse
import numpy as np
import requests

F = "https://fapi.binance.com"
MIN_QV = 3_000_000
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def klines(sym, itv="1h", limit=500):
    k = requests.get(F + "/fapi/v1/klines",
                     params={"symbol": sym, "interval": itv, "limit": limit}, timeout=20).json()
    if not isinstance(k, list) or len(k) < 60:
        return None
    return (np.array([float(x[1]) for x in k]), np.array([float(x[2]) for x in k]),
            np.array([float(x[3]) for x in k]), np.array([float(x[4]) for x in k]),
            np.array([float(x[7]) for x in k]))


def swings(h, l, n=3):
    """좌우 n봉보다 높은/낮은 봉 = 스윙 고점/저점."""
    hi, lo = [], []
    for i in range(n, len(h) - n):
        if h[i] == h[i-n:i+n+1].max(): hi.append(h[i])
        if l[i] == l[i-n:i+n+1].min(): lo.append(l[i])
    return np.array(hi), np.array(lo)


def cluster(vals, cur, tol=0.012):
    """가까운 값끼리 묶어 (평균가, 터치횟수) 목록. tol=1.2% 이내면 같은 선."""
    if not len(vals): return []
    out = []
    for v in sorted(vals):
        for g in out:
            if abs(v / g[0] - 1) <= tol:
                g[1].append(v); g[0] = float(np.mean(g[1])); break
        else:
            out.append([float(v), [float(v)]])
    return sorted([(g[0], len(g[1])) for g in out], key=lambda x: -x[1])


def vpoc(c, v, bins=40):
    """거래대금이 가장 많이 쌓인 가격 구간."""
    lo, hi = c.min(), c.max()
    if hi <= lo: return None
    idx = np.clip(((c - lo) / (hi - lo) * (bins - 1)).astype(int), 0, bins - 1)
    agg = np.bincount(idx, weights=v, minlength=bins)
    b = int(np.argmax(agg))
    return lo + (hi - lo) * (b + 0.5) / bins


def analyze(sym, quiet=False):
    d = klines(sym)
    if d is None: return None
    o, h, l, c, v = d
    cur = float(c[-1])
    ma25, ma99 = c[-25:].mean(), c[-99:].mean()
    sh, sl = swings(h, l)
    res = [x for x in cluster(sh, cur) if x[0] > cur * 1.002][:4]
    sup = [x for x in cluster(sl, cur) if x[0] < cur * 0.998]
    sup = sorted(sup, key=lambda x: -x[0])[:4]
    poc = vpoc(c[-200:], v[-200:])
    # 최근 스윙: 직전 100봉 저점 → 고점
    w = slice(-100, None)
    swlo, swhi = float(l[w].min()), float(h[w].max())
    rng = swhi - swlo
    fib = {p: swhi - rng * p for p in (0.382, 0.5, 0.618)} if rng > 0 else {}
    pull = (cur / swhi - 1) * 100
    uptrend = cur > ma25 > ma99
    if not quiet:
        print(f"\n{'='*74}")
        print(f"[{sym[:-4]}]  현재 {cur:.6g}")
        print(f"  추세: MA25 {ma25:.6g} / MA99 {ma99:.6g}  → "
              f"{'★상승추세(현재>MA25>MA99)' if uptrend else '추세 아님'}")
        print(f"  최근 100시간 저점 {swlo:.6g} → 고점 {swhi:.6g}  |  고점 대비 {pull:+.1f}%")
        print(f"\n  저항선 (위)")
        for p, n in res: print(f"    {p:.6g}   {(p/cur-1)*100:+6.1f}%   터치 {n}회")
        if not res: print("    (100시간 내 위쪽 스윙 고점 없음 = 신고가권)")
        print(f"  ── 현재가 {cur:.6g} ──")
        print(f"  지지선 (아래)")
        for p, n in sup: print(f"    {p:.6g}   {(p/cur-1)*100:+6.1f}%   터치 {n}회")
        if poc: print(f"\n  거래량 집중대(VPOC) {poc:.6g}  ({(poc/cur-1)*100:+.1f}%)  ← 실질 지지/저항")
        if fib:
            print(f"  피보나치 되돌림 (저점 {swlo:.6g} ~ 고점 {swhi:.6g})")
            for p, x in fib.items(): print(f"    {p*100:.1f}%  {x:.6g}  ({(x/cur-1)*100:+.1f}%)")
    return dict(sym=sym, cur=cur, uptrend=uptrend, pull=pull, res=res, sup=sup, poc=poc)


def scan(top=12):
    tick = requests.get(F + "/fapi/v1/ticker/24hr", timeout=30).json()
    cand = [d["symbol"] for d in tick
            if d["symbol"].endswith("USDT") and float(d["quoteVolume"]) >= MIN_QV]
    print(f"후보 {len(cand)}종목에서 눌림목 찾는 중...", flush=True)
    hits = []
    for i, s in enumerate(cand):
        try:
            r = analyze(s, quiet=True)
            if r and r["uptrend"] and -18 <= r["pull"] <= -4 and r["sup"]:
                near = (r["sup"][0][0] / r["cur"] - 1) * 100
                hits.append((s[:-4], r["pull"], near, r["sup"][0][1],
                             r["res"][0][0] if r["res"] else None, r["cur"]))
        except Exception:
            pass
        time.sleep(0.02)
        if (i + 1) % 60 == 0: print(f"  {i+1}/{len(cand)}", flush=True)
    hits.sort(key=lambda x: x[2], reverse=True)     # 지지선에 가까운 순
    print(f"\n{'='*80}")
    print("  눌림목 (상승추세 유지 + 고점 대비 -4~-18% 되돌림)")
    print(f"{'='*80}")
    print(f"{'종목':<12}{'현재가':>12}{'고점대비':>10}{'가장가까운지지':>14}{'터치':>6}{'위쪽저항':>12}")
    for s, pull, near, tn, res, cur in hits[:top]:
        print(f"{s:<12}{cur:>12.6g}{pull:>+9.1f}%{near:>13.1f}%{tn:>6}"
              f"{(res if res else 0):>12.6g}")
    if not hits: print("  해당 종목 없음")
    print(f"\n  총 {len(hits)}종목. '가장가까운지지'는 현재가에서 지지선까지의 거리다.")
    print("  ※ 계산값이다. 이 선들이 지켜진다는 보장은 없다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*"); ap.add_argument("--scan", action="store_true")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    if a.scan or not a.symbols:
        scan(a.top); return
    for s in a.symbols:
        analyze(s.upper() if s.upper().endswith("USDT") else s.upper() + "USDT")


if __name__ == "__main__":
    main()
