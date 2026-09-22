"""PREREG_STOP10.md 실행 — 손절선 명목 40%(현행) vs 5%(증거금-10%) vs 7.5%(증거금-15%) 짝비교.

Run: .venv/Scripts/python.exe scripts/stop_level_eval.py
"""
import csv, os, sys, time, json
from datetime import datetime, timezone, timedelta
import numpy as np
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LEDGERS = [("원본", "data/margin_short_ledger.csv"), ("완화", "data/margin_short_wide_ledger.csv")]
LEV = 2.0
FEE_SIDE = 0.0006      # 명목, 체결 1회당
STOP_EXTRA = 0.0005    # 손절 슬리피지, 명목
LEVELS = [40.0, 5.0, 7.5]     # 명목 %. 2026-09-22: PREREG_STOP10.md — 주 비교 5.0(증거금-10%), 7.5(증거금-15%,병기)
BASE = 40.0
MAIN = 5.0
SEED, BOOT, BLOCK_DAYS = 20260918, 4000, 7
CACHE = "data/_stop_kl_cache.json"
SLEEP = 0.35

_cache = {}
if os.path.exists(CACHE):
    try:
        _cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        _cache = {}


def klines(sym, t0ms, t1ms):
    key = f"{sym}|{t0ms}|{t1ms}"
    if key in _cache:
        return _cache[key]
    rows, cur = [], t0ms
    for _ in range(20):
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}"
               f"&interval=5m&startTime={cur}&endTime={t1ms}&limit=1500")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=25) as r:
                    d = json.load(r)
                break
            except Exception as e:
                if attempt == 3:
                    print(f"    ! {sym} 조회 실패 {e}", flush=True)
                    return None
                time.sleep(3 * (attempt + 1))
        if not d:
            break
        rows += [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in d]
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 300_000
        time.sleep(SLEEP)
    _cache[key] = rows
    time.sleep(SLEEP)
    return rows


def load_trades():
    out = []
    for eng, path in LEDGERS:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    pct = float(r["net_pnl_pct_margin"])
                    tin = datetime.fromisoformat(r["entry_time"])
                    tout = datetime.fromisoformat(r["exit_time"])
                except Exception:
                    continue
                if pct < -100:
                    continue
                out.append(dict(eng=eng, sym=r["symbol"], tin=tin, tout=tout, pct=pct,
                                fund=float(r.get("funding_usdt") or 0),
                                margin=float(r.get("margin_usdt") or 0), reason=r.get("reason", "")))
    out.sort(key=lambda x: x["tin"])
    return out


def simulate(t, kl, stop_nom):
    """손절선 stop_nom(명목 %)일 때 증거금 기준 순손익 %. 원 거래와 같은 펀딩을 쓴다."""
    t0 = int(t["tin"].timestamp() * 1000)
    t1 = int(t["tout"].timestamp() * 1000)
    base = [k for k in kl if k[0] <= t0]
    if not base:
        return None
    entry = base[-1][4]
    if entry <= 0:
        return None
    trig = entry * (1 + stop_nom / 100.0)
    for ts, o, hi, lo, cl in kl:
        if ts <= t0 or ts > t1:
            continue
        if hi >= trig:
            # 손절 체결: 명목 손실 = stop_nom + 슬리피지, 왕복 수수료
            nom = -(stop_nom + STOP_EXTRA * 100) - FEE_SIDE * 100 * 2
            pct = nom * LEV
            fund_pct = (t["fund"] / t["margin"] * 100) if t["margin"] else 0.0
            return pct + fund_pct
    return t["pct"]     # 손절 미발동 → 원 거래 그대로


def blocks(days):
    b = (days - days.min()) // BLOCK_DAYS
    ub = np.unique(b)
    return ub, {u: np.nonzero(b == u)[0] for u in ub}


def boot_mean(x, d, seed=SEED, iters=BOOT):
    ub, idx = blocks(d)
    rng = np.random.default_rng(seed)
    ms = np.empty(iters)
    for k in range(iters):
        sel = np.concatenate([idx[ub[p]] for p in rng.integers(0, len(ub), len(ub))])
        ms[k] = x[sel].mean()
    return np.percentile(ms, [2.5, 97.5]), ms.std(ddof=1), len(ub)


def desc(tag, x):
    x = np.asarray(x)
    w5 = np.sort(x)[:5].mean()
    return (f"  {tag}  평균 {x.mean():+7.2f}%  중앙 {np.median(x):+7.2f}%  승률 {(x>0).mean()*100:5.1f}%  "
            f"최악5평균 {w5:+7.2f}%  최대손실 {x.min():+7.2f}%")


def main():
    tr = load_trades()
    print(f"[손절선 재검정: 증거금 -10%/-15%] 사전등록 docs/PREREG_STOP10.md (커밋 c8143a3)")
    print(f"청산 완료 숏 거래 {len(tr)}건 (이상치 제외). 5분봉 경로 재현 중...\n", flush=True)

    ok = []
    for i, t in enumerate(tr):
        kl = klines(t["sym"], int(t["tin"].timestamp() * 1000) - 300_000,
                    int(t["tout"].timestamp() * 1000) + 300_000)
        if not kl:
            continue
        sim = {s: simulate(t, kl, s) for s in LEVELS}
        if any(v is None for v in sim.values()):
            continue
        t["sim"] = sim
        ok.append(t)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(tr)} ...", flush=True)
            try:
                json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
            except Exception:
                pass
    try:
        json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
    except Exception:
        pass

    print(f"\n재현 성공 {len(ok)}건 / {len(tr)}건")
    if len(ok) < 100:
        print(f"  ▶ S5: 재현 건수 100 미만 — **판정 보류**")
        return

    real = np.array([t["pct"] for t in ok])
    b40 = np.array([t["sim"][BASE] for t in ok])
    gap = b40.mean() - real.mean()
    print(f"\n[재현 품질] 실제 평균 {real.mean():+.2f}%  vs  40% 재현 평균 {b40.mean():+.2f}%  "
          f"괴리 {gap:+.2f}%p")
    if abs(gap) > 3.0:
        print("  ▶ 괴리 3%p 초과 — 사전등록 4항에 따라 **이 판정은 무효**. 아래는 참고로만 출력한다.")
        invalid = True
    else:
        print("  ▶ 괴리 3%p 이내 — 재현 품질 합격")
        invalid = False

    print("\n" + "=" * 74)
    print(desc("실제      ", real))
    for s in LEVELS:
        x = np.array([t["sim"][s] for t in ok])
        print(desc(f"손절 {s:4.0f}%(명목)", x))

    days = np.array([t["tin"].timestamp() // 86400 for t in ok])
    print("\n" + "=" * 74)
    print(f"짝차이 (대안 − 40% 재현), {BLOCK_DAYS}일 블록 {BOOT}회, 시드 {SEED}")
    verdict = None
    for s in LEVELS:
        if s == BASE:
            continue
        d = np.array([t["sim"][s] - t["sim"][BASE] for t in ok])
        (clo, chi), se, nb = boot_mean(d, days)
        m = 2.802 * se
        ruined = sum(1 for t in ok if t["sim"][BASE] > 0 and t["sim"][s] < 0)
        saved = sum(1 for t in ok if t["sim"][s] - t["sim"][BASE] > 1e-9)
        tag = "주 판정" if s == MAIN else "강건성 병기(승격 금지)"
        print(f"\n  손절 {s:.0f}%  [{tag}]")
        print(f"    짝차이 {d.mean():+.2f}%p   95% CI [{clo:+.2f}, {chi:+.2f}]   MDE {m:.2f}%p   (블록 {nb}개)")
        print(f"    조여서 구한 건 {saved}건 / 조여서 망친 건(40%엔 이익→손절) {ruined}건")
        for eng in ("원본", "완화"):
            de = [t["sim"][s] - t["sim"][BASE] for t in ok if t["eng"] == eng]
            print(f"    └ {eng}봇 {len(de)}건  짝차이 {np.mean(de):+.2f}%p")
        if s == MAIN:
            pt = d.mean()
            if pt > 0 and clo > 0:
                verdict = "손절 30% 우위 확인 (S1)"
            elif pt > 0 and abs(pt) >= m:
                verdict = "유망 — 전방 재확인 (S2)"
            elif abs(pt) < m:
                verdict = "판별 불가 (S3)"
            else:
                verdict = "기각 — 40% 유지 (S4)"
            ds = {}
            for t in ok:
                k = int(t["tin"].timestamp() // 86400)
                ds[k] = ds.get(k, 0) + (t["sim"][s] - t["sim"][BASE])
            tot = sum(abs(v) for v in ds.values())
            if tot > 0:
                print(f"    최대기여 단일 진입일 비중 {max(abs(v) for v in ds.values())/tot*100:.1f}%")

    print("\n" + "=" * 74)
    print(f"  ▶ 판정 (주 비교 30%): {verdict}")
    if invalid:
        print("  ▶ 단, 재현 품질 미달로 **무효** — 위 판정을 근거로 쓰지 않는다.")
    print("  ※ 통과해도 실거래 자동 반영 없음 — 손절선 변경은 사용자 결정 (CLAUDE.md 6항).")


if __name__ == "__main__":
    main()
