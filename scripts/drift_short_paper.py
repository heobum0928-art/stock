"""
구조적 하락 숏 — **모의 전방검증** (drift_short_paper). 2026-09-10.
docs/PREREG_DRIFT_PAPER.md 기준 그대로.

**주문 없음. 실거래 아님. 읽기 전용 API만 쓴다.**
백테스트(research/m5bt/drift_short.py)를 실시간으로 재현한다.

규칙(사전등록 §1, 변경 금지):
  진입 방아쇠 없음 — 24h 거래대금 ≥ 300만 USDT, 상장 30일 초과인 종목 전부
  같은 심볼은 직전 진입 30일 경과 후 재진입
  보유 30일 / 손절 명목 +40% / 레버리지 2배 / 펀딩·수수료 실측
  동시 200칸, 초과 시 선착순(FIFO) — 성적으로 고르지 않는다
  건당 명목 5 USDT

Run: .venv/Scripts/python.exe scripts/drift_short_paper.py [--once]
watchdog 상주(POLL_SEC=1800).
"""
import sys, os, json, time, math, argparse, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
UTC = timezone.utc; KST = timezone(timedelta(hours=9))
FAPI = "https://fapi.binance.com"

# ── 사전등록 상수 (변경 금지) ──────────────────────────────
MIN_QV       = 3_000_000
NEWLIST_DAYS = 30
HOLD_DAYS    = 30
STOP_NOM     = 40.0
LEV          = 2.0
NOTIONAL     = 5.0          # 바이낸스 최소 주문금액
MAX_SLOTS    = 200
FEE_NOM      = 0.10         # 왕복 명목 %
POLL_SEC     = 1800
REENTRY_DAYS = 30

POS  = ROOT / "data" / "drift_short_paper_pos.json"
OUT  = ROOT / "data" / "drift_short_paper_trades.csv"
LAST = ROOT / "data" / "drift_short_paper_lastentry.json"
LOGF = ROOT / "logs" / "drift_short_paper.log"

LOGF.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [DRIFT] %(message)s",
                    handlers=[logging.FileHandler(LOGF, encoding="utf-8"),
                              logging.StreamHandler(sys.stdout)])
log = logging.getLogger()
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def get(path, params=None, tries=3):
    import requests
    for i in range(tries):
        try:
            r = requests.get(FAPI + path, params=params or {}, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429) or "-1003" in r.text or "-1015" in r.text:
                log.error(f"★API 제한 저촉 {r.status_code} {r.text[:120]} — 사전등록 §3 하드 중단 조건")
                return None
        except Exception:
            pass
        time.sleep(1.0)
    return None


def jload(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d


def jsave(p, o):
    t = Path(str(p) + ".tmp"); t.write_text(json.dumps(o), encoding="utf-8"); os.replace(t, p)


def universe():
    """진입 자격: 거래 중 / USDT / 24h 거래대금 ≥ 300만 / 상장 30일 초과."""
    info = get("/fapi/v1/exchangeInfo")
    tick = get("/fapi/v1/ticker/24hr")
    if not info or not tick:
        return None
    now_ms = int(time.time() * 1000)
    ok_age = {s["symbol"] for s in info["symbols"]
              if s["status"] == "TRADING" and s["symbol"].endswith("USDT")
              and now_ms - int(s.get("onboardDate", 0)) > NEWLIST_DAYS * 86400_000}
    out = {}
    for d in tick:
        s = d["symbol"]
        if s in ok_age and float(d["quoteVolume"]) >= MIN_QV and float(d["lastPrice"]) > 0:
            out[s] = float(d["lastPrice"])
    return out


def funding_sum(sym, s_ms, e_ms):
    f = get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": s_ms, "endTime": e_ms, "limit": 1000})
    if f is None: return None
    return sum(float(x["fundingRate"]) for x in f) * 100.0


def stop_touched(sym, since_ms, stop_px):
    """지난 폴링 이후 5분봉 고가가 손절선에 닿았는지. 닿았으면 그 시각(ms)."""
    k = get("/fapi/v1/klines", {"symbol": sym, "interval": "5m", "startTime": since_ms, "limit": 500})
    if not k: return None
    for c in k:
        if float(c[2]) >= stop_px:
            return int(c[0])
    return None


def write_row(r):
    new = not OUT.exists()
    OUT.parent.mkdir(exist_ok=True)
    import csv
    with OUT.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(r.keys()))
        if new: w.writeheader()
        w.writerow(r)


def cycle():
    pos  = jload(POS, {})
    last = jload(LAST, {})
    now  = time.time(); now_ms = int(now * 1000)

    uni = universe()
    if uni is None:
        log.warning("유니버스 조회 실패 — 이번 사이클 건너뜀"); return

    # ── 청산 판정 ──────────────────────────────────
    closed = 0
    for sym in list(pos.keys()):
        p = pos[sym]
        stop_px = p["entry_px"] * (1 + STOP_NOM / 100)
        exit_px = exit_ms = reason = None

        t = stop_touched(sym, int(p["last_check_ms"]), stop_px)
        if t is not None:
            exit_px, exit_ms, reason = stop_px, t, "손절+40%"
        elif now - p["entry_ts"] >= HOLD_DAYS * 86400:
            cur = uni.get(sym)
            if cur is None:
                k = get("/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 1})
                cur = float(k[-1][4]) if k else None
            if cur:
                exit_px, exit_ms, reason = cur, now_ms, f"만기{HOLD_DAYS}일"

        if exit_px is None:
            p["last_check_ms"] = now_ms
            continue

        f = funding_sum(sym, int(p["entry_ms"]), exit_ms)
        if f is None:
            log.warning(f"{sym} 펀딩 조회 실패 — 다음 사이클 재시도"); continue
        price_nom = (1 - exit_px / p["entry_px"]) * 100      # 숏
        net_marg  = (price_nom - FEE_NOM + f) * LEV
        write_row(dict(
            entry_time=datetime.fromtimestamp(p["entry_ts"], KST).isoformat(),
            exit_time=datetime.fromtimestamp(exit_ms / 1000, KST).isoformat(),
            symbol=sym, entry_price=p["entry_px"], exit_price=exit_px,
            hold_h=round((exit_ms / 1000 - p["entry_ts"]) / 3600, 2), reason=reason,
            price_pnl_pct_nom=round(price_nom, 4), funding_pct_nom=round(f, 4),
            fee_pct_nom=FEE_NOM, net_pnl_pct_margin=round(net_marg, 4),
            notional_usdt=NOTIONAL, margin_usdt=round(NOTIONAL / LEV, 4),
            net_pnl_usdt=round(net_marg / 100 * NOTIONAL / LEV, 4)))
        log.info(f"청산 {sym} {reason} 가격{price_nom:+.1f}% 펀딩{f:+.2f}% → 증거금 {net_marg:+.1f}%")
        del pos[sym]; closed += 1

    # ── 진입 (선착순, 성적으로 고르지 않는다) ─────────
    free = MAX_SLOTS - len(pos)
    opened = 0
    if free > 0:
        # ★ 2026-09-10: 첫 사이클엔 수백 개가 동시에 자격을 얻으므로 "선착순"의 순서가
        #   정해지지 않는다. 사전순으로 자르면 A~M만 들어가고 N~Z가 통째로 빠진다 —
        #   성적 기반은 아니지만 임의의 치우침이다. **고정 시드 무작위**로 섞는다.
        #   시드 고정이라 재현 가능하고, 성적과 무관하다(사전등록 §1 "성적으로 고르지 않는다").
        import random as _r
        cands = [s for s in uni
                 if s not in pos
                 and now - float(last.get(s, 0)) >= REENTRY_DAYS * 86400]
        _r.Random(20260910).shuffle(cands)
        for s in cands[:free]:
            pos[s] = dict(entry_px=uni[s], entry_ts=now, entry_ms=now_ms, last_check_ms=now_ms)
            last[s] = now; opened += 1

    jsave(POS, pos); jsave(LAST, last)
    log.info(f"사이클 완료 | 후보 {len(uni)} | 진입 {opened} | 청산 {closed} | 보유 {len(pos)}/{MAX_SLOTS}")

    if len(pos) > MAX_SLOTS:
        log.error(f"★칸 상한 초과 {len(pos)}>{MAX_SLOTS} — 사전등록 §3 하드 중단 조건")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    log.info(f"=== 구조적 하락 숏 모의 시작 (명목 {NOTIONAL} / {MAX_SLOTS}칸 / {HOLD_DAYS}일 / 손절+{STOP_NOM:.0f}%) ===")
    log.info("주문 없음. 모의 전용. 판정일 2026-12-10 (PREREG_DRIFT_PAPER.md)")
    while True:
        try:
            cycle()
        except Exception as e:
            log.exception(f"사이클 오류: {e}")
        if a.once: break
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
