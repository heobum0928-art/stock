"""
BTC 국면별 사이징 축소 판정 — docs/PREREG_BTC_REGIME_SIZING.md 기준.

**계산기다. 추천이 아니다.** 규칙·문턱·판정기준은 사전등록 문서에 고정돼 있고
이 스크립트는 그대로 계산만 한다.

규칙: 진입 시점 BTC 24h 수익률 r24 >= +2.0% 이면 "강세 구간"(증거금 50%), 아니면 평시(100%).
표본: data/shadow_trades.csv 의 V1_notrail 청산 완료 건.
통계: (강세 평균 − 평시 평균) 증거금 기준 %, 7일 날짜블록 부트스트랩 4,000회 시드 20260916.

Run: .venv/Scripts/python.exe scripts/btc_regime_sizing_eval.py
"""
import sys, os, csv, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
FAPI = "https://fapi.binance.com"
TRADES = ROOT / "data" / "shadow_trades.csv"
BTC_CACHE = ROOT / "data" / "_btc_1h_regime_cache.json"

# ── 사전등록 고정값 (변경 금지) ──
VARIANT = "V1_notrail"
BULL_THRESHOLD_PCT = 2.0      # r24 >= +2.0% → 강세
BULL_SIZE = 0.5               # 강세 구간 증거금 50%
LOOKBACK_H = 24
BLOCK_DAYS = 7
BOOT_ITERS = 4000
SEED = 20260916
MIN_BULL_N = 15               # R3
MAX_DAY_SHARE = 50.0          # R4 (%)


def fetch_btc_1h(start_ms, end_ms):
    if BTC_CACHE.exists():
        try:
            c = json.loads(BTC_CACHE.read_text(encoding="utf-8"))
            if c.get("start") <= start_ms and c.get("end") >= end_ms:
                return {int(k): v for k, v in c["bars"].items()}
        except Exception:
            pass
    bars = {}
    cur = start_ms
    while cur < end_ms:
        r = requests.get(FAPI + "/fapi/v1/klines",
                         params={"symbol": "BTCUSDT", "interval": "1h",
                                 "startTime": cur, "limit": 1000}, timeout=20)
        k = r.json()
        if not isinstance(k, list) or not k:
            break
        for x in k:
            bars[int(x[0])] = float(x[4])          # open_time → close
        nxt = int(k[-1][0]) + 3600_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    BTC_CACHE.write_text(json.dumps({"start": start_ms, "end": end_ms,
                                     "bars": {str(k): v for k, v in bars.items()}}),
                         encoding="utf-8")
    return bars


def r24_at(bars, ts_ms):
    """진입 직전 '확정된' 1시간봉 기준 24h 수익률. 미래 봉 사용 금지."""
    hour = (ts_ms // 3600_000) * 3600_000
    cur_open = hour - 3600_000                      # 직전 완성봉
    prev_open = cur_open - LOOKBACK_H * 3600_000
    c_now, c_prev = bars.get(cur_open), bars.get(prev_open)
    if c_now is None or c_prev is None or c_prev <= 0:
        return None
    return (c_now / c_prev - 1) * 100


def block_bootstrap_diff(bull_days, flat_days, all_days, rng):
    """7일 날짜블록 복원추출 → (강세평균 − 평시평균) 분포."""
    day_list = sorted(all_days)
    if not day_list:
        return np.array([])
    d0 = day_list[0]
    blocks = {}
    for d in day_list:
        b = (d - d0).days // BLOCK_DAYS
        blocks.setdefault(b, []).append(d)
    keys = list(blocks)
    out = []
    for _ in range(BOOT_ITERS):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        bv, fv = [], []
        for i in pick:
            for d in blocks[keys[i]]:
                bv.extend(bull_days.get(d, []))
                fv.extend(flat_days.get(d, []))
        if bv and fv:
            out.append(float(np.mean(bv) - np.mean(fv)))
    return np.array(out)


def main():
    rows = [r for r in csv.DictReader(open(TRADES, encoding="utf-8"))
            if r.get("variant") == VARIANT and (r.get("net_pnl_pct_margin") or "") != ""]
    if not rows:
        print("표본 없음"); return

    times = []
    for r in rows:
        t = datetime.fromisoformat(r["entry_time"]).astimezone(timezone.utc)
        times.append(int(t.timestamp() * 1000))
    start_ms = min(times) - (LOOKBACK_H + 3) * 3600_000
    end_ms = max(times) + 2 * 3600_000
    print(f"[데이터] {VARIANT} {len(rows)}건 | BTC 1시간봉 로드 중...", flush=True)
    bars = fetch_btc_1h(start_ms, end_ms)
    print(f"  BTC 봉 {len(bars)}개")

    recs, skipped = [], 0
    for r, ts in zip(rows, times):
        r24 = r24_at(bars, ts)
        if r24 is None:
            skipped += 1
            continue
        d = datetime.fromisoformat(r["entry_time"]).astimezone(KST).date()
        recs.append(dict(sym=r["symbol"], day=d, r24=r24,
                         pnl=float(r["net_pnl_pct_margin"]),
                         bull=r24 >= BULL_THRESHOLD_PCT))
    bull = [x for x in recs if x["bull"]]
    flat = [x for x in recs if not x["bull"]]
    print(f"  매칭 {len(recs)}건 (BTC봉 누락 {skipped}건 제외)\n")

    print("=" * 74)
    print(f"[BTC 국면별 사이징 — PREREG_BTC_REGIME_SIZING.md 판정]")
    print(f"  국면 정의: 진입시점 BTC 24h 수익률 >= +{BULL_THRESHOLD_PCT}% → 강세(증거금 {BULL_SIZE*100:.0f}%)")
    print("=" * 74)
    allr = np.array([x["r24"] for x in recs])
    pct = float((allr < BULL_THRESHOLD_PCT).mean() * 100)
    print(f"  문턱 +{BULL_THRESHOLD_PCT}% = 이 표본 r24 분포의 {pct:.0f} 퍼센타일 (보고만, 문턱 재조정 안 함)")
    print(f"  강세 구간 {len(bull)}건 / 평시 {len(flat)}건\n")

    if not bull or not flat:
        print("  한쪽 구간이 비어 판정 불가"); return

    mb = float(np.mean([x["pnl"] for x in bull]))
    mf = float(np.mean([x["pnl"] for x in flat]))
    diff = mb - mf
    print(f"  강세 평균  {mb:+8.2f}%  (증거금 기준)  승률 {sum(1 for x in bull if x['pnl']>0)/len(bull)*100:5.1f}%")
    print(f"  평시 평균  {mf:+8.2f}%  (증거금 기준)  승률 {sum(1 for x in flat if x['pnl']>0)/len(flat)*100:5.1f}%")
    print(f"  차이(강세−평시)  {diff:+8.2f}%p")

    rng = np.random.default_rng(SEED)
    bd, fd, days = {}, {}, set()
    for x in recs:
        days.add(x["day"])
        (bd if x["bull"] else fd).setdefault(x["day"], []).append(x["pnl"])
    boot = block_bootstrap_diff(bd, fd, days, rng)
    if len(boot):
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"  95% CI [{lo:+.2f}, {hi:+.2f}]%p — {BLOCK_DAYS}일 날짜블록 {BOOT_ITERS}회, 시드 {SEED}, 유효 {len(boot)}회")
    else:
        lo = hi = float("nan")
        print("  부트스트랩 불가")

    # R4 — 최대기여 단일 날짜
    day_tot = {}
    for x in recs:
        w = BULL_SIZE if x["bull"] else 1.0
        day_tot[x["day"]] = day_tot.get(x["day"], 0.0) + (w - 1.0) * x["pnl"]
    tot = sum(day_tot.values())
    if abs(tot) > 1e-9:
        top_day = max(day_tot, key=lambda d: abs(day_tot[d]))
        share = abs(day_tot[top_day]) / sum(abs(v) for v in day_tot.values()) * 100
    else:
        top_day, share = None, 0.0

    # 사이징 규칙 적용 효과(산술적 귀결, 보고용)
    base = float(np.mean([x["pnl"] for x in recs]))
    ruled = float(np.mean([(BULL_SIZE if x["bull"] else 1.0) * x["pnl"] for x in recs]))
    print(f"\n  [사이징 적용 효과 — 보고용]")
    print(f"    baseline 건당 기여 평균  {base:+.2f}%  →  규칙 적용  {ruled:+.2f}%   (차 {ruled-base:+.2f}%p)")
    w10 = sorted(recs, key=lambda x: x["pnl"])[:10]
    wb = float(np.mean([x["pnl"] for x in w10]))
    wr = float(np.mean([(BULL_SIZE if x["bull"] else 1.0) * x["pnl"] for x in w10]))
    print(f"    최악 10건 평균           {wb:+.2f}%  →  {wr:+.2f}%   (개선 {(1-wr/wb)*100 if wb else 0:+.1f}%)")
    for nm, g in (("강세", bull), ("평시", flat)):
        w5 = sorted(g, key=lambda x: x["pnl"])[:5]
        print(f"    R5 {nm} 최악5 평균        {np.mean([x['pnl'] for x in w5]):+.2f}%")

    print(f"\n  판정:")
    r1 = diff < 0
    r2 = (not np.isnan(hi)) and hi < 0
    r3 = len(bull) >= MIN_BULL_N
    r4 = share < MAX_DAY_SHARE
    print(f"    R1 차이 점추정 < 0            {diff:+.2f}%p            → {'충족' if r1 else '미충족'}")
    print(f"    R2 95% CI 상한 < 0            {hi:+.2f}%p            → {'충족' if r2 else '미충족'}")
    print(f"    R3 강세 표본 >= {MIN_BULL_N}건           {len(bull)}건               → {'충족' if r3 else '미충족(표본 부족)'}")
    print(f"    R4 최대기여 단일일 < 50%      {share:.1f}% ({top_day})   → {'충족' if r4 else '미충족'}")
    if not r3:
        v = "표본 부족 — 판정 보류"
    elif r1 and r2 and r4:
        v = "후보 승격 (단, 실거래 반영은 사용자 결정 — 문서 6절)"
    elif r1:
        v = "보류 — 방향은 맞으나 CI가 0을 배제하지 못함"
    else:
        v = "기각 — 부호가 반대"
    print(f"  ▶ 종합: {v}")
    print("\n  ※ 승률·중앙값은 판정에 쓰지 않는다(CLAUDE.md 4항). 숫자에는 잣대(증거금 기준)를 같이 적을 것.")
    print("  ※ 표본 독립성 한계는 PREREG 0절 참조 — 통과해도 즉시 채택하지 않는다.")


if __name__ == "__main__":
    main()
