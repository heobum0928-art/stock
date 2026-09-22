"""PREREG_LSRATIO_CONTRARIAN.md 실행 — 롱숏비율 극단 역발상 신호.

Run: .venv/Scripts/python.exe scripts/lsratio_contrarian_eval.py
"""
import csv, os, sys, time, json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import numpy as np
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = "data/futures_signals.csv"
CACHE = "data/_lsratio_kl.json"
TOP_N = 200
TRAIL_DAYS = 3
MIN_TRAIL_N = 260
PCT_HI, PCT_LO = 95, 5
COOLDOWN_S = 12 * 3600
COST = 0.12
MAIN_H = 60
HS = [(60, "1시간"), (240, "4시간"), (1440, "24시간")]
SEED, BOOT = 20260923, 4000
SLEEP = 0.25

_cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def http_json(url):
    for a in range(4):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def klines_15m(sym, t0, t1):
    key = f"{sym}|{t0}|{t1}"
    if key in _cache:
        return _cache[key]
    rows, cur = [], t0
    for _ in range(10):
        d = http_json(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m"
                      f"&startTime={cur}&endTime={t1}&limit=1500")
        if not d:
            break
        rows += [[int(k[0]), float(k[4])] for k in d]
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 900_000
        time.sleep(SLEEP)
    _cache[key] = rows
    return rows


def load():
    per = defaultdict(list)
    with open(SRC, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").timestamp()
                ls = float(r["ls_ratio"])
                tk = float(r["taker_ratio"])
            except Exception:
                continue
            per[r["coin"]].append((t, ls, tk))
    for c in per:
        per[c].sort()
    order = sorted(per, key=lambda c: -len(per[c]))[:TOP_N]
    return {c: per[c] for c in order}


def find_events(rows, col_idx):
    """rows: sorted (t, ls, tk). col_idx: 1=ls_ratio, 2=taker_ratio."""
    ts = np.array([r[0] for r in rows])
    val = np.array([r[col_idx] for r in rows])
    hi_ev, lo_ev = [], []
    last_hi, last_lo = -1e18, -1e18
    for i in range(len(rows)):
        w0 = ts[i] - TRAIL_DAYS * 86400
        lo_i = np.searchsorted(ts, w0, side="left")
        n = i - lo_i
        if n < MIN_TRAIL_N:
            continue
        window = val[lo_i:i]
        p_hi = np.percentile(window, PCT_HI)
        p_lo = np.percentile(window, PCT_LO)
        if val[i] >= p_hi and ts[i] - last_hi >= COOLDOWN_S:
            hi_ev.append(ts[i]); last_hi = ts[i]
        elif val[i] <= p_lo and ts[i] - last_lo >= COOLDOWN_S:
            lo_ev.append(ts[i]); last_lo = ts[i]
    return hi_ev, lo_ev


def price_at_and_after(sym, kl, t0):
    t0ms = int(t0 * 1000)
    base = [k for k in kl if k[0] <= t0ms]
    if not base:
        return None, {}
    p0 = base[-1][1]
    out = {}
    for m, _ in HS:
        tgt = t0ms + m * 60_000
        fut = [k for k in kl if k[0] >= tgt]
        out[m] = (fut[0][1] / p0 - 1) * 100 if fut else None
    return p0, out


def boot_diff(x1, d1, x2, d2, seed=SEED, iters=BOOT):
    def blocks(days):
        b = (days - days.min()) // 7
        ub = np.unique(b)
        return ub, {u: np.nonzero(b == u)[0] for u in ub}
    u1, i1 = blocks(d1); u2, i2 = blocks(d2)
    rng = np.random.default_rng(seed)
    ms = np.empty(iters)
    for k in range(iters):
        s1 = np.concatenate([i1[u1[p]] for p in rng.integers(0, len(u1), len(u1))])
        s2 = np.concatenate([i2[u2[p]] for p in rng.integers(0, len(u2), len(u2))])
        ms[k] = x1[s1].mean() - x2[s2].mean()
    return np.percentile(ms, [2.5, 97.5]), ms.std(ddof=1)


def main():
    per = load()
    print("[롱숏비율 역발상] 사전등록 docs/PREREG_LSRATIO_CONTRARIAN.md (커밋 bd09336)")
    print(f"코인 {len(per)}개(표본수 상위 {TOP_N}), 트레일링 {TRAIL_DAYS}일, 문턱 {PCT_HI}/{PCT_LO}퍼센타일\n")

    all_hi, all_lo = [], []   # (coin, t, ls_val)
    for k, (coin, rows) in enumerate(per.items()):
        hi, lo = find_events(rows, 1)
        all_hi += [(coin, t) for t in hi]
        all_lo += [(coin, t) for t in lo]
        if (k + 1) % 40 == 0:
            print(f"  신호 탐지 {k+1}/{len(per)} 종목, 누적 롱쏠림 {len(all_hi)} 숏쏠림 {len(all_lo)}", flush=True)
    print(f"\n총 신호: 극단 롱쏠림 {len(all_hi)}건 / 극단 숏쏠림 {len(all_lo)}건\n")

    lo0 = min(min(t for _, t in all_hi), min(t for _, t in all_lo))
    hi0 = max(max(t for _, t in all_hi), max(t for _, t in all_lo))

    def gather(events, tag):
        out = []
        by_coin = defaultdict(list)
        for c, t in events:
            by_coin[c].append(t)
        for j, (coin, times) in enumerate(by_coin.items()):
            sym = coin + "USDT"
            kl = klines_15m(sym, int(min(times) * 1000) - 900_000,
                            int(max(times) * 1000) + 1440 * 60_000 + 900_000)
            if not kl:
                continue
            for t in times:
                p0, fut = price_at_and_after(sym, kl, t)
                if p0 is None or fut.get(MAIN_H) is None:
                    continue
                out.append((coin, t, fut))
            if (j + 1) % 40 == 0:
                print(f"    {tag} 가격조회 {j+1}/{len(by_coin)} 종목", flush=True)
        return out

    print("극단 롱쏠림 다리 가격 조회 중...")
    hi_out = gather(all_hi, "롱쏠림")
    print("극단 숏쏠림 다리 가격 조회 중...")
    lo_out = gather(all_lo, "숏쏠림")
    try:
        json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
    except Exception:
        pass

    print(f"\n유효 매칭: 롱쏠림 {len(hi_out)}건 / 숏쏠림 {len(lo_out)}건\n")
    if len(hi_out) < 100 or len(lo_out) < 100:
        print("  ▶ L5: 표본 부족 — 판정 보류")
        return

    xh = np.array([o[2][MAIN_H] for o in hi_out])
    dh = np.array([int(o[1] // 86400) for o in hi_out])
    xl = np.array([o[2][MAIN_H] for o in lo_out])
    dl = np.array([int(o[1] // 86400) for o in lo_out])

    print("=" * 78)
    print(f"{'구간':>6} {'롱쏠림후 원시수익':>16} {'숏쏠림후 원시수익':>16} {'차이(숏쏠림-롱쏠림)':>18}")
    for m, lab in HS:
        a = np.array([o[2][m] for o in hi_out if o[2].get(m) is not None])
        b = np.array([o[2][m] for o in lo_out if o[2].get(m) is not None])
        if len(a) and len(b):
            print(f"{lab:>6} {a.mean():>+15.3f}% {b.mean():>+15.3f}% {b.mean()-a.mean():>+17.3f}%p")

    stat = xl.mean() - xh.mean()
    (lo_ci, hi_ci), se = boot_diff(xl, dl, xh, dh)
    mde = 2.802 * se
    print(f"\n주 통계량(1시간, 숏쏠림평균 - 롱쏠림평균) = {stat:+.3f}%p")
    print(f"95% CI [{lo_ci:+.3f}, {hi_ci:+.3f}]  (7일 블록, {BOOT}회, 시드 {SEED})  MDE {mde:.3f}%p")

    if stat > 0 and lo_ci > 0:
        v = "가설 확인 — 다음은 실행 가능성 검증 (L1)"
    elif stat > 0 and abs(stat) >= mde:
        v = "유망 (L2)"
    elif abs(stat) < mde:
        v = "판별 불가 (L3)"
    else:
        v = "기각 (L4)"
    print(f"\n  ▶ 가설 존재 여부 판정: {v}")

    # 실행 가능성: 각 다리를 실제로 거래했을 때 비용 차감 후
    short_leg = -xh - COST      # 롱쏠림 → 숏
    long_leg = xl - COST        # 숏쏠림 → 롱

    def boot_mean(x, d, seed=SEED, iters=BOOT):
        b = (d - d.min()) // 7
        ub = np.unique(b); idx = {u: np.nonzero(b == u)[0] for u in ub}
        rng = np.random.default_rng(seed); ms = np.empty(iters)
        for k in range(iters):
            sel = np.concatenate([idx[ub[p]] for p in rng.integers(0, len(ub), len(ub))])
            ms[k] = x[sel].mean()
        return np.percentile(ms, [2.5, 97.5])
    slo, shi = boot_mean(short_leg, dh)
    llo, lhi = boot_mean(long_leg, dl)
    print(f"\n실행 가능성(비용 {COST}% 차감 후):")
    print(f"  롱쏠림→숏 다리: 평균 {short_leg.mean():+.3f}%  95% CI [{slo:+.3f}, {shi:+.3f}]  "
          f"→ {'통과' if short_leg.mean()>0 and slo>0 else '미통과'}")
    print(f"  숏쏠림→롱 다리: 평균 {long_leg.mean():+.3f}%  95% CI [{llo:+.3f}, {lhi:+.3f}]  "
          f"→ {'통과' if long_leg.mean()>0 and llo>0 else '미통과'}")
    both_pass = short_leg.mean() > 0 and slo > 0 and long_leg.mean() > 0 and llo > 0
    print(f"\n  ▶ 최종: {'실행 가능 — 전방 모의로' if (v.startswith('가설 확인')) and both_pass else '신호는 있어도 비용 대비 무의미 / 또는 가설 자체 미확인'}")

    print("\n" + "=" * 78 + "\n[병기 — 판정에 쓰지 않음]")
    months = defaultdict(list)
    for o in hi_out:
        months[datetime.fromtimestamp(o[1]).strftime("%Y-%m")].append(("hi", o[2][MAIN_H]))
    for o in lo_out:
        months[datetime.fromtimestamp(o[1]).strftime("%Y-%m")].append(("lo", o[2][MAIN_H]))
    for mo in sorted(months):
        h = [v for k, v in months[mo] if k == "hi"]; l = [v for k, v in months[mo] if k == "lo"]
        if h and l:
            print(f"  {mo}: 롱쏠림n={len(h)} {np.mean(h):+.2f}% / 숏쏠림n={len(l)} {np.mean(l):+.2f}%  "
                  f"차 {np.mean(l)-np.mean(h):+.2f}%p")
    for tag, out in (("BTC/ETH", [o for o in hi_out + lo_out if o[0] in ("BTC", "ETH")]),):
        pass
    majors_hi = [o[2][MAIN_H] for o in hi_out if o[0] in ("BTC", "ETH")]
    majors_lo = [o[2][MAIN_H] for o in lo_out if o[0] in ("BTC", "ETH")]
    alts_hi = [o[2][MAIN_H] for o in hi_out if o[0] not in ("BTC", "ETH")]
    alts_lo = [o[2][MAIN_H] for o in lo_out if o[0] not in ("BTC", "ETH")]
    if majors_hi and majors_lo:
        print(f"\n  메이저(BTC/ETH): 롱쏠림 n={len(majors_hi)} {np.mean(majors_hi):+.2f}% / "
              f"숏쏠림 n={len(majors_lo)} {np.mean(majors_lo):+.2f}%")
    print(f"  알트: 롱쏠림 n={len(alts_hi)} {np.mean(alts_hi):+.2f}% / 숏쏠림 n={len(alts_lo)} {np.mean(alts_lo):+.2f}%")

    print("\n  ※ 통과해도 실거래 자동 반영 없음 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
