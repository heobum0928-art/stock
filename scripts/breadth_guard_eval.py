"""PREREG_BREADTH_GUARD.md 실행 — 알트 동반 상승(시장 폭) 가드 검정.

검정 A: breadth_6h >= 0.70 구간 진입을 걸렀으면 나았나 (군간 비교, 날짜블록 부트스트랩)
검정 B: 같은 거래에 절반청산(-20%에서 절반)을 소급 적용했을 때 짝차이 (군별)

Run: .venv/Scripts/python.exe scripts/breadth_guard_eval.py
"""
import csv, os, sys, time
from datetime import datetime, timezone, timedelta
import numpy as np
import urllib.request, json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
LEDGERS = [("원본", "data/margin_short_ledger.csv"), ("완화", "data/margin_short_wide_ledger.csv")]
BREADTH = "data/breadth_events.csv"
THR = 0.70            # 사전등록 고정
COL = "breadth_6h"    # 사전등록 고정
MAX_STALE_MIN = 30    # 사전등록 고정
LEV = 2.0
FEE_SIDE = 0.0006
HALF_TRIM_PCT = 20.0  # 증거금 기준 역행 %
SEED, BOOT = 20260918, 4000
BLOCK_DAYS = 7
KL_CACHE = "data/_breadth_kl_cache.json"


# ---------- 로드 ----------
def load_breadth():
    ts, val = [], {c: [] for c in ("breadth_1h", "breadth_3h", "breadth_6h")}
    with open(BREADTH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            except Exception:
                continue
            ok = True
            row = {}
            for c in val:
                try:
                    row[c] = float(r[c])
                except Exception:
                    ok = False
            if not ok:
                continue
            ts.append(t.timestamp())
            for c in val:
                val[c].append(row[c])
    o = np.argsort(ts)
    return np.array(ts)[o], {c: np.array(v)[o] for c, v in val.items()}


def load_trades():
    out = []
    for eng, path in LEDGERS:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    tin = datetime.fromisoformat(r["entry_time"])
                    tout = datetime.fromisoformat(r["exit_time"])
                    pct = float(r["net_pnl_pct_margin"])
                    mg = float(r["margin_usdt"])
                except Exception:
                    continue
                if pct < -100:   # 사전등록 이상치 규칙 (증거금 기준)
                    continue
                out.append(dict(eng=eng, sym=r["symbol"], tin=tin, tout=tout,
                                pct=pct, margin=mg, reason=r.get("reason", "")))
    out.sort(key=lambda x: x["tin"])
    return out


# ---------- 부트스트랩 ----------
def blocks(days):
    b = (days - days.min()) // BLOCK_DAYS
    ub = np.unique(b)
    return ub, {u: np.nonzero(b == u)[0] for u in ub}


def boot_diff(xa, da, xb, db, seed=SEED, iters=BOOT):
    """두 군 평균 차이(A-B)의 날짜블록 부트스트랩 CI."""
    uba, ia = blocks(da)
    ubb, ib = blocks(db)
    rng = np.random.default_rng(seed)
    ms = np.empty(iters)
    for k in range(iters):
        sa = np.concatenate([ia[uba[p]] for p in rng.integers(0, len(uba), len(uba))])
        sb = np.concatenate([ib[ubb[p]] for p in rng.integers(0, len(ubb), len(ubb))])
        ms[k] = xa[sa].mean() - xb[sb].mean()
    return np.percentile(ms, [2.5, 97.5]), ms.std(ddof=1), len(uba), len(ubb)


def boot_mean(x, d, seed=SEED, iters=BOOT):
    ub, idx = blocks(d)
    rng = np.random.default_rng(seed)
    ms = np.empty(iters)
    for k in range(iters):
        sel = np.concatenate([idx[ub[p]] for p in rng.integers(0, len(ub), len(ub))])
        ms[k] = x[sel].mean()
    return np.percentile(ms, [2.5, 97.5]), ms.std(ddof=1), len(ub)


def mde(se):
    """양측 95%·검정력 80% 최소검출효과."""
    return 2.802 * se


# ---------- 5분봉 ----------
_cache = {}
if os.path.exists(KL_CACHE):
    try:
        _cache = json.load(open(KL_CACHE, encoding="utf-8"))
    except Exception:
        _cache = {}


def klines(sym, t0ms, t1ms):
    key = f"{sym}|{t0ms}|{t1ms}"
    if key in _cache:
        return _cache[key]
    rows = []
    cur = t0ms
    for _ in range(40):
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}"
               f"&interval=5m&startTime={cur}&endTime={t1ms}&limit=1500")
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                d = json.load(r)
        except Exception as e:
            print(f"    ! {sym} 봉 조회 실패 {e}", flush=True)
            return None
        if not d:
            break
        rows += [[int(k[0]), float(k[2]), float(k[3]), float(k[4])] for k in d]
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 300_000
        time.sleep(0.12)
    _cache[key] = rows
    return rows


def halftrim_pnl(tr, entry_px):
    """절반청산 적용 손익(증거금 기준 %). 경로를 5분봉 고가로 재현."""
    t0 = int(tr["tin"].timestamp() * 1000)
    t1 = int(tr["tout"].timestamp() * 1000)
    kl = klines(tr["sym"], t0, t1 + 300_000)
    if not kl:
        return None
    # 숏 역행 = 고가 상승. 증거금 기준 역행% = (high/entry-1)*100*LEV
    trig = entry_px * (1 + HALF_TRIM_PCT / 100.0 / LEV)
    hit = None
    for ts, hi, lo, cl in kl:
        if ts < t0 or ts > t1:
            continue
        if hi >= trig:
            hit = trig
            break
    if hit is None:
        return tr["pct"]          # -20% 미도달 → 원본과 동일
    # 절반은 -20%에서 청산, 절반은 원 청산가
    half_pct = -HALF_TRIM_PCT
    rest_pct = tr["pct"]
    extra_fee = FEE_SIDE * LEV * 100 * 0.5   # 절반분 청산 수수료 1회 추가(증거금 기준 %)
    return 0.5 * half_pct + 0.5 * rest_pct - extra_fee


# ---------- 보고 ----------
def stat_line(tag, x):
    x = np.asarray(x)
    if not len(x):
        return f"  {tag}: 0건"
    w5 = np.sort(x)[:5].mean() if len(x) >= 5 else np.sort(x).mean()
    return (f"  {tag}: {len(x)}건  평균 {x.mean():+.2f}%  중앙 {np.median(x):+.2f}%  "
            f"승률 {(x>0).mean()*100:.1f}%  최악5평균 {w5:+.2f}%")


def main():
    bts, bval = load_breadth()
    trades = load_trades()
    print(f"[시장 폭 가드] 사전등록 PREREG_BREADTH_GUARD.md (커밋 c5773b2)")
    print(f"breadth 로그 {len(bts)}행  {datetime.fromtimestamp(bts[0],KST):%Y-%m-%d} ~ "
          f"{datetime.fromtimestamp(bts[-1],KST):%Y-%m-%d}")
    print(f"청산 완료 숏 거래 {len(trades)}건 (이상치 제외 후)\n")

    # 매칭: 진입 시각 직전 행
    miss = 0
    for t in trades:
        ts = t["tin"].timestamp()
        i = np.searchsorted(bts, ts, side="right") - 1
        if i < 0 or (ts - bts[i]) > MAX_STALE_MIN * 60:
            t["b"] = None
            miss += 1
        else:
            t["b"] = {c: float(bval[c][i]) for c in bval}
    ok = [t for t in trades if t["b"] is not None]
    print(f"breadth 매칭 성공 {len(ok)}건 / 실패 {miss}건 (커버리지 {len(ok)/len(trades)*100:.1f}%)")

    allb = bval[COL]
    pctile = (allb < THR).mean() * 100
    print(f"문턱 {COL} >= {THR:.2f} → 전체 로그 분포의 {pctile:.1f} 퍼센타일 "
          f"(중앙 {np.median(allb):.3f}, 평균 {allb.mean():.3f})\n")

    hi = [t for t in ok if t["b"][COL] >= THR]
    lo = [t for t in ok if t["b"][COL] < THR]

    # ===== 검정 A =====
    print("=" * 68)
    print("검정 A — 동반 상승 중 진입 vs 그 외")
    xh = np.array([t["pct"] for t in hi]); dh = np.array([t["tin"].timestamp() // 86400 for t in hi])
    xl = np.array([t["pct"] for t in lo]); dl = np.array([t["tin"].timestamp() // 86400 for t in lo])
    print(stat_line(f"{COL} >= {THR} (동반 상승)", xh))
    print(stat_line(f"{COL} <  {THR} (그 외)    ", xl))
    for eng in ("원본", "완화"):
        eh = [t["pct"] for t in hi if t["eng"] == eng]
        el = [t["pct"] for t in lo if t["eng"] == eng]
        print(f"   └ {eng}봇  동반상승 {len(eh)}건 {np.mean(eh) if eh else float('nan'):+.2f}%  "
              f"/ 그 외 {len(el)}건 {np.mean(el) if el else float('nan'):+.2f}%")

    if len(xh) < 15 or len(xl) < 15:
        print(f"\n  ▶ A5: 표본 부족 (동반상승 {len(xh)}건 / 그 외 {len(xl)}건, 기준 15건) — 판정 보류")
        verdictA = "표본부족"
        pt = (xl.mean() - xh.mean()) if len(xh) and len(xl) else float("nan")
        print(f"     (참고) 점추정 {pt:+.2f}%p — 판정에 쓰지 않음")
    else:
        pt = xl.mean() - xh.mean()
        (clo, chi), se, nba, nbb = boot_diff(xl, dl, xh, dh)
        m = mde(se)
        print(f"\n  점추정 (그 외 − 동반상승) = {pt:+.2f}%p")
        print(f"  95% CI [{clo:+.2f}, {chi:+.2f}]%p  — {BLOCK_DAYS}일 블록 {nba}/{nbb}개, {BOOT}회, 시드 {SEED}")
        print(f"  MDE(95%·80%) = {m:.2f}%p")
        if pt > 0 and clo > 0:
            verdictA = "가드 효과 확인 (A1)"
        elif pt > 0 and abs(pt) >= m:
            verdictA = "유망 — 전방 재확인 (A2)"
        elif abs(pt) < m:
            verdictA = "판별 불가 (A3)"
        else:
            verdictA = "기각 (A4)"
        print(f"  ▶ 판정 A: {verdictA}")

    # 강건성 병기 (주 판정 아님)
    print("\n  [강건성 병기 — 주 판정 승격 금지]")
    for c in ("breadth_6h", "breadth_3h", "breadth_1h"):
        for th in (0.60, 0.70, 0.80):
            h = [t["pct"] for t in ok if t["b"][c] >= th]
            l = [t["pct"] for t in ok if t["b"][c] < th]
            if len(h) < 5 or len(l) < 5:
                print(f"    {c} >= {th:.2f}: 표본 부족 ({len(h)}/{len(l)})")
                continue
            print(f"    {c} >= {th:.2f}: 동반 {len(h)}건 {np.mean(h):+.2f}% / 그 외 {len(l)}건 "
                  f"{np.mean(l):+.2f}%  차 {np.mean(l)-np.mean(h):+.2f}%p")

    # ===== 검정 B =====
    print("\n" + "=" * 68)
    print("검정 B — 절반청산(-20% 절반 정리) 소급 적용, 짝차이")
    print("  5분봉 재조회 중...", flush=True)
    for t in ok:
        t0 = int(t["tin"].timestamp() * 1000)
        t1 = int(t["tout"].timestamp() * 1000)
        kl = klines(t["sym"], t0 - 300_000, t1 + 300_000)
        if not kl:
            t["ht"] = None
            continue
        base = [k for k in kl if k[0] <= t0]
        if not base:
            t["ht"] = None
            continue
        entry_px = base[-1][3]      # 진입 시각이 속한 봉의 종가를 진입가 근사
        t["ht"] = halftrim_pnl(t, entry_px)
    try:
        json.dump(_cache, open(KL_CACHE, "w", encoding="utf-8"))
    except Exception:
        pass

    for name, grp in (("동반 상승일", hi), ("그 외", lo)):
        g = [t for t in grp if t.get("ht") is not None]
        if len(g) < 15:
            print(f"  {name}: {len(g)}건 — 표본 부족 (B4)")
            if g:
                d = np.array([t["ht"] - t["pct"] for t in g])
                print(f"     (참고) 짝차이 평균 {d.mean():+.2f}%p, 발동 {sum(1 for x in d if abs(x)>1e-9)}건 — 판정에 쓰지 않음")
            continue
        d = np.array([t["ht"] - t["pct"] for t in g])
        dd = np.array([t["tin"].timestamp() // 86400 for t in g])
        (clo, chi), se, nb = boot_mean(d, dd)
        fired = sum(1 for x in d if abs(x) > 1e-9)
        print(f"  {name}: {len(g)}건 (절반청산 발동 {fired}건)")
        print(f"     원본 평균 {np.mean([t['pct'] for t in g]):+.2f}%  →  "
              f"절반청산 평균 {np.mean([t['ht'] for t in g]):+.2f}%")
        print(f"     짝차이 {d.mean():+.2f}%p  95% CI [{clo:+.2f}, {chi:+.2f}]  MDE {mde(se):.2f}%p  "
              f"({BLOCK_DAYS}일 블록 {nb}개)")

    print("\n  ※ B는 참고용. V8 정식 판정은 PREREG_HALFTRIM.md(2026-10-15) 전방 표본이며,")
    print("    여기 결과로 그 판정일·기준을 앞당기거나 바꾸지 않는다.")
    print("\n  ※ 통과해도 실거래 자동 반영 없음 — 사용자 결정 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
