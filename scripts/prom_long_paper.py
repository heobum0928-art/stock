"""
PROM 롱 모의봇 (prom_long_paper) — 순수 모의, 매매 API 미호출.

★ 2026-08-30 신설. 사전등록: docs/PREREG_PROM_LONG.md (봇 가동 전 작성)

배경: PROM 실거래 숏 이력(2026-08-12~08-30, 6건) 3승 3패, 합계 -66.58 USDT,
손실 3건이 전부 -20 이상으로 크다. 사후추적 2건 모두 "잘 파셨습니다"(숏 정리 후에도
계속 오름) — "이 코인은 되돌아오지 않는다 → 롱이 낫다"는 발상이 자연스러우나,
그 논리 구조(미러롱)는 훨씬 큰 표본(n=1228)으로 이미 두 번 기각됐다. 표본이 작을수록
신중해야 하므로 PREREG_PROM_LONG.md의 엄격한 기준(20건, 99%CI 병기, 최대기여 제외
검사, 11/15 마감 — 미루지 않음)을 그대로 따른다.

규칙(PREREG_PROM_LONG.md 1절 — 변경 금지):
  대상 = PROMUSDT 단일 종목(다른 코인 추가 금지 — 그 순간 미러롱 재탕)
  신호 = 7시간 상승률 >= 15% (완화봇 하한, 상한 없음)
  방향 = 롱 / 보유 = 48시간 고정 / 손절·트레일링 = 없음 / 레버리지 1배 / 쿨다운 12h

★ 내장 대조군: 신호 진입 1건마다 같은 시각에 무작위 코인 1건을 동시 진입한다
  (quietpump_long_paper.py와 동일 설계 — 시장 국면 통제).

★ mfe/mae(보유구간 실제 고가·저가)를 처음부터 기록한다 — quietpump이 08-30에
  뒤늦게 추가한 것을 여기선 처음부터 넣는다. 청산규칙 설계에 바로 쓸 수 있게.

★ 순수 모의: 매매 API 미호출. 포트 47261.
상태 data/prom_long_pos.json | 기록 data/prom_long_trades.csv
로그 logs/prom_long_paper.log
Run: python scripts/prom_long_paper.py
"""
import sys, os, atexit, time, json, csv, socket, logging, random
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
KST = timezone(timedelta(hours=9))

_sock = None
def _single():
    global _sock
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        _sock.bind(("127.0.0.1", 47261))
    except OSError:
        print("[ERROR] prom_long_paper 이미 실행 중 (포트 47261)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [PROMLONG] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler("logs/prom_long_paper.log", encoding="utf-8")])
log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"

# ── 규칙 상수 (사전등록 1절 — 변경 금지) ────────────────────────────────────
TARGET_SYM = "PROMUSDT"
LOOKBACK_H = 7           # 7시간 상승률
PUMP_PCT = 15.0          # 하한 (완화봇과 동일), 상한 없음
HOLD_H = 48              # 고정 보유 (숏 봇들과 동일 — 직접비교 목적)
COOLDOWN_H = 12
LEVERAGE = 1.0
FEE_SIDE = 0.0006
POLL_SEC = 300

POS_PATH = ROOT / "data" / "prom_long_pos.json"
TRADES_PATH = ROOT / "data" / "prom_long_trades.csv"
COOLDOWN_PATH = ROOT / "data" / "prom_long_cooldown.json"

TRADE_FIELDS = ["entry_time", "exit_time", "symbol", "kind", "entry_price", "exit_price",
                "r7_pct", "price_pnl_pct", "funding_pct", "fee_pct", "net_pnl_pct",
                "hold_h", "reason", "btc_entry", "btc_exit", "mfe_pct", "mae_pct"]


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, o):
    tmp = Path(p).with_suffix(".tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def universe():
    try:
        r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=15)
        return sorted(s["symbol"] for s in r.json()["symbols"]
                      if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
                      and s["symbol"].endswith("USDT"))
    except Exception as e:
        log.warning(f"유니버스 조회 실패: {e}")
        return []


def klines(sym, limit):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/klines",
                         params={"symbol": sym, "interval": "5m", "limit": limit}, timeout=8)
        if r.status_code != 200:
            return None
        k = r.json()
        return k if len(k) >= limit else None
    except Exception:
        return None


def price(sym):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/price", params={"symbol": sym}, timeout=8)
        return float(r.json()["price"]) if r.status_code == 200 else None
    except Exception:
        return None


def check_signal():
    """PREREG_PROM_LONG.md 1절: 7시간 상승률 >= 15%. 원본 숏봇과 같은 LOOKBACK_H,
    같은 하한(완화봇 PUMP_PCT). 반환 (신호여부, r7%, 현재가) — 조회실패시 (None,...)."""
    bars = LOOKBACK_H * 12  # 5분봉 개수
    k = klines(TARGET_SYM, bars + 1)
    if k is None:
        return None, None, None
    c = [float(x[4]) for x in k]
    r7 = (c[-1] / c[0] - 1.0) * 100.0
    hit = r7 >= PUMP_PCT
    return hit, r7, c[-1]


def excursion_pct(sym, entry_px, start_ms, end_ms):
    """보유구간 5분봉 고가/저가로 mfe(최고)·mae(최저) 수익률. 롱 기준(가격 상승=+).
    quietpump_long_paper.py의 동일 함수와 같은 설계(2026-08-30)."""
    try:
        r = requests.get(f"{FAPI}/fapi/v1/klines",
                         params={"symbol": sym, "interval": "5m",
                                 "startTime": start_ms, "endTime": end_ms, "limit": 500},
                         timeout=10)
        if r.status_code != 200:
            return None, None
        k = r.json()
        if not k:
            return None, None
        hi = max(float(x[2]) for x in k)
        lo = min(float(x[3]) for x in k)
        return round((hi / entry_px - 1.0) * 100.0, 3), round((lo / entry_px - 1.0) * 100.0, 3)
    except Exception as e:
        log.warning(f"고저 조회 실패 {sym}: {e}")
        return None, None


def funding_pct(sym, start_ms, end_ms):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/fundingRate",
                         params={"symbol": sym, "startTime": start_ms, "endTime": end_ms, "limit": 1000},
                         timeout=8)
        if r.status_code != 200:
            return 0.0
        return sum(float(x["fundingRate"]) for x in r.json()) * 100.0
    except Exception:
        return 0.0


def log_trade(row):
    try:
        new = not TRADES_PATH.exists()
        with open(TRADES_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        log.error(f"기록 실패({e}) — 포지션 정리는 계속: {row.get('symbol')}")


def open_paper(positions, sym, kind, px, r7, now, btc):
    positions[sym + "|" + kind] = {
        "symbol": sym, "kind": kind, "entry_price": px,
        "entry_ts": now, "entry_iso": datetime.now(KST).isoformat(),
        "exit_ts": now + HOLD_H * 3600,
        "r7_pct": round(r7, 3) if r7 is not None else None,
        "btc_entry": btc,
    }


def main():
    positions = _load(POS_PATH, {})
    cooldown = _load(COOLDOWN_PATH, {})
    now0 = time.time()
    cooldown = {k: v for k, v in cooldown.items() if v > now0}
    rng = random.Random(20260830)
    uni = universe()
    last_uni = time.time()

    log.info(f"PROM 롱 모의봇 시작 [🔵모의(dry) — 매매 API 미호출] "
             f"대상={TARGET_SYM} 신호: {LOOKBACK_H}h>=+{PUMP_PCT}% "
             f"→ 롱 {HOLD_H}h 고정, 손절없음, 레버리지 {LEVERAGE:.0f}배 | 대조군 동시진입")

    while True:
        try:
            now = time.time()
            if now - last_uni >= 6 * 3600:
                fresh = universe()
                if fresh:
                    uni = fresh
                last_uni = now

            btc = price("BTCUSDT")

            # ── 1) 만기 청산 ────────────────────────────────────────────────
            for key in list(positions.keys()):
                p = positions[key]
                if now < p["exit_ts"]:
                    continue
                px = price(p["symbol"])
                if px is None:
                    log.warning(f"청산가 조회 실패 {p['symbol']} — 다음 사이클 재시도")
                    continue
                price_pnl = (px / p["entry_price"] - 1.0) * 100.0 * LEVERAGE
                fnd = funding_pct(p["symbol"], int(p["entry_ts"] * 1000), int(now * 1000))
                fee = 2 * FEE_SIDE * 100.0 * LEVERAGE
                net = price_pnl - fnd * LEVERAGE - fee
                mfe, mae = excursion_pct(p["symbol"], p["entry_price"],
                                          int(p["entry_ts"] * 1000), int(now * 1000))
                log_trade(dict(
                    entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                    symbol=p["symbol"], kind=p["kind"],
                    entry_price=p["entry_price"], exit_price=px,
                    r7_pct=p.get("r7_pct"),
                    price_pnl_pct=round(price_pnl, 3), funding_pct=round(fnd, 4),
                    fee_pct=round(fee, 3), net_pnl_pct=round(net, 3),
                    hold_h=round((now - p["entry_ts"]) / 3600, 2), reason=f"{HOLD_H}h만기",
                    btc_entry=p.get("btc_entry"), btc_exit=btc,
                    mfe_pct=mfe, mae_pct=mae))
                log.info(f"[모의청산] {p['symbol']}({p['kind']}) @{px:g} "
                         f"순손익 {net:+.2f}% (가격 {price_pnl:+.2f} 펀딩 -{fnd*LEVERAGE:.2f} 수수료 -{fee:.2f})")
                del positions[key]
            _save(POS_PATH, positions)

            # ── 2) 신호 탐지 (PROM만) ───────────────────────────────────────
            if (TARGET_SYM + "|signal") not in positions and cooldown.get(TARGET_SYM, 0) <= now:
                hit, r7, px = check_signal()
                if hit:
                    cooldown[TARGET_SYM] = now + COOLDOWN_H * 3600
                    open_paper(positions, TARGET_SYM, "signal", px, r7, now, btc)
                    log.info(f"[모의진입:신호] {TARGET_SYM} @{px:g} 7h {r7:+.2f}%")

                    # ── 대조군: 같은 시각 무작위 코인 1건 ──────────────────
                    cands = [s for s in uni
                             if s != TARGET_SYM and (s + "|random") not in positions
                             and cooldown.get(s, 0) <= now]
                    if cands:
                        rs = rng.choice(cands)
                        rpx = price(rs)
                        if rpx:
                            cooldown[rs] = now + COOLDOWN_H * 3600
                            open_paper(positions, rs, "random", rpx, None, now, btc)
                            log.info(f"[모의진입:대조] {rs} @{rpx:g}")
                    _save(POS_PATH, positions)

            cooldown = {k: v for k, v in cooldown.items() if v > time.time()}
            _save(COOLDOWN_PATH, cooldown)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
