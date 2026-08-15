"""
OI(미결제약정) 다이버전스 숏 페이퍼 트레이더 (oi_divergence_short_paper) — 순수 모의, 매매 API 미호출.

목적(2026-08-15): 레딧/학술자료 리서치에서 나온 신규 후보 — "가격은 오르는데 OI는 안 늘거나
줄어드는 펌프는 숏커버링/약한매수 위주라 반전이 잘 된다"는 가설을 실자본 없이 forward 검증.
아직 벤더 콘텐츠 외 검증된 백테스트 근거가 없어 순수 가설 단계 (docs/would_change_log.md 참고).

설계: margin_short_trader.py와 **청산규칙을 동일하게**(스탑-40%/트레일+15%→10%/48h만기) 맞춰서
진입필터(펌프기준 15%+ & OI다이버전스)만 다르게 한 결과를 순수 비교할 수 있게 함 — 나중에
"OI필터를 얹으면 기존 마진숏보다 나은가"를 청산로직 차이 없이 판단하기 위함.

신호: 1시간봉 기준 최근 7시간 가격변동 >= PUMP_MIN(15%) AND 같은 기간 OI변동 <= OI_MAX(0%)
      (가격은 올랐는데 OI는 그대로거나 줄었다 = 숏커버링성 약한 펌프로 추정)

★ 순수 모의: 매매 API 미호출, live_guard 미연동. 포트 47254.
상태 data/oi_div_paper_pos.json | 기록 data/oi_div_paper_trades.csv | 로그 logs/oi_divergence_short_paper.log
Run: python scripts/oi_divergence_short_paper.py
"""
import sys, os, atexit, time, json, csv, socket, logging
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
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try: _sock.bind(("127.0.0.1", 47254))
    except OSError: print("[ERROR] oi_divergence_short_paper 이미 실행 중 (포트 47254)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [OIDIV] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/oi_divergence_short_paper.log", encoding="utf-8")])
log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"
POLL_SEC = 300
PUMP_WINDOW_H = 7
PUMP_MIN_PCT = 15.0     # margin_short(30~40%)보다 낮게 잡아 더 많은 후보 관찰 — 순수 가설검증 단계
OI_MAX_CHG_PCT = 0.0    # 같은 기간 OI변동이 이 이하(정체~감소)면 다이버전스로 판정
MIN_QUOTE_VOL_24H = 3_000_000

STOP_PCT = 40.0          # margin_short_trader.py와 동일 청산규칙(진입필터만 비교하기 위함)
TRAIL_TRIGGER_PCT = 15.0
TRAIL_GIVEBACK_PCT = 10.0
MAX_HOLD_H = 48
COOLDOWN_H = 24

POS_PATH = ROOT / "data" / "oi_div_paper_pos.json"
TRADES_PATH = ROOT / "data" / "oi_div_paper_trades.csv"


def _load(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d
def _save(p, o):
    tmp = Path(p).with_suffix(".tmp"); tmp.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(p)


def perp_universe():
    try:
        r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=10).json()
        return [s["baseAsset"] for s in r.get("symbols", [])
                if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"]
    except Exception as e:
        log.warning(f"선물목록 조회 실패: {e}"); return []


def quote_vol_24h(coin):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/24hr", params={"symbol": f"{coin}USDT"}, timeout=8).json()
        return float(r.get("quoteVolume", 0))
    except Exception:
        return 0.0


def check_signal(coin):
    """(신호?, price_chg_pct, oi_chg_pct, 현재가) — 1시간봉 기준 최근 PUMP_WINDOW_H."""
    sym = f"{coin}USDT"
    try:
        kr = requests.get(f"{FAPI}/fapi/v1/klines", params={"symbol": sym, "interval": "1h", "limit": PUMP_WINDOW_H + 1}, timeout=8)
        if kr.status_code != 200: return False, 0, 0, 0
        k = kr.json()
        if len(k) < PUMP_WINDOW_H + 1: return False, 0, 0, 0
        px_now = float(k[-1][4]); px_then = float(k[0][1])
        if px_then <= 0: return False, 0, 0, 0
        price_chg = (px_now / px_then - 1) * 100

        oir = requests.get(f"{FAPI}/futures/data/openInterestHist",
                            params={"symbol": sym, "period": "1h", "limit": PUMP_WINDOW_H + 1}, timeout=8)
        if oir.status_code != 200: return False, price_chg, 0, px_now
        oi = oir.json()
        if len(oi) < 2: return False, price_chg, 0, px_now
        oi_now = float(oi[-1]["sumOpenInterestValue"]); oi_then = float(oi[0]["sumOpenInterestValue"])
        if oi_then <= 0: return False, price_chg, 0, px_now
        oi_chg = (oi_now / oi_then - 1) * 100

        hit = price_chg >= PUMP_MIN_PCT and oi_chg <= OI_MAX_CHG_PCT
        return hit, price_chg, oi_chg, px_now
    except Exception:
        return False, 0, 0, 0


def log_trade(row):
    new = not TRADES_PATH.exists()
    with open(TRADES_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["entry_time", "exit_time", "symbol", "price_chg_pct", "oi_chg_pct",
                                           "entry_price", "exit_price", "pnl_pct", "mfe_pct", "mae_pct", "reason"])
        if new: w.writeheader()
        w.writerow(row)


def main():
    positions = _load(POS_PATH, {})
    cooldown = {}
    uni = perp_universe()
    log.info(f"OI다이버전스 숏 페이퍼 시작 — 선물유니버스 {len(uni)}코인, "
             f"{PUMP_WINDOW_H}h+{PUMP_MIN_PCT:.0f}%펌프 & OI변동<={OI_MAX_CHG_PCT:.0f}% → "
             f"스탑-{STOP_PCT:.0f}%/트레일+{TRAIL_TRIGGER_PCT:.0f}%→{TRAIL_GIVEBACK_PCT:.0f}%/{MAX_HOLD_H}h만기 | 순수모의(매매0)")
    try:
        from bithumb import notify
        notify.send(f"📉 OI다이버전스 숏 페이퍼 시작 — 순수모의(매매0), 신규 가설검증(레딧리서치 1순위 후보)")
    except Exception: pass

    day = datetime.now(KST).date()
    while True:
        try:
            now = time.time()
            if datetime.now(KST).date() != day:
                day = datetime.now(KST).date()
                uni = perp_universe() or uni

            # 1) 포지션 점검(청산) — 신규진입 스캔보다 먼저 처리
            if positions:
                for sym in list(positions.keys()):
                    p = positions[sym]
                    try:
                        r = requests.get(f"{FAPI}/fapi/v1/ticker/price", params={"symbol": sym}, timeout=8)
                        px = float(r.json()["price"]) if r.status_code == 200 else None
                    except Exception:
                        px = None
                    if not px or px <= 0:
                        continue
                    p["min_p"] = min(p["min_p"], px)  # 숏이라 유리한 방향=하락
                    p["max_p"] = max(p["max_p"], px)
                    entry = p["entry_price"]
                    favorable_pct = (1 - p["min_p"] / entry) * 100
                    pnl = (1 - px / entry) * 100
                    hold_h = (now - p["entry_ts"]) / 3600

                    reason = None
                    if px >= entry * (1 + STOP_PCT / 100):
                        reason = f"스탑-{STOP_PCT:.0f}%"
                    elif favorable_pct >= TRAIL_TRIGGER_PCT:
                        trail_level = p["min_p"] * (1 + TRAIL_GIVEBACK_PCT / 100)
                        if px >= trail_level:
                            reason = f"트레일(최고{favorable_pct:.0f}%→{pnl:.0f}%)"
                    if reason is None and hold_h >= MAX_HOLD_H:
                        reason = f"{MAX_HOLD_H}h만기"

                    if reason:
                        mfe = (1 - p["min_p"] / entry) * 100
                        mae = (1 - p["max_p"] / entry) * 100
                        log_trade(dict(entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(), symbol=sym,
                                       price_chg_pct=p["price_chg"], oi_chg_pct=p["oi_chg"],
                                       entry_price=entry, exit_price=px, pnl_pct=round(pnl, 2),
                                       mfe_pct=round(mfe, 2), mae_pct=round(mae, 2), reason=reason))
                        log.warning(f"[모의]청산 {sym} @{px:g} {reason} pnl={pnl:+.2f}%")
                        cooldown[sym] = now + COOLDOWN_H * 3600
                        del positions[sym]
                _save(POS_PATH, positions)

            # 2) 신규 신호 스캔
            for coin in uni:
                sym = f"{coin}USDT"
                if sym in positions or cooldown.get(sym, 0) > now:
                    continue
                if quote_vol_24h(coin) < MIN_QUOTE_VOL_24H:
                    continue
                hit, price_chg, oi_chg, px = check_signal(coin)
                if not hit or px <= 0:
                    continue
                positions[sym] = {
                    "entry_ts": now, "entry_price": px, "price_chg": round(price_chg, 1),
                    "oi_chg": round(oi_chg, 1), "min_p": px, "max_p": px,
                    "entry_iso": datetime.now(KST).isoformat(),
                }
                log.warning(f"[모의]진입 {sym} @{px:g} {PUMP_WINDOW_H}h+{price_chg:.0f}% OI{oi_chg:+.1f}% → 다이버전스 숏")
                try:
                    from bithumb import notify
                    notify.send(f"🎯 OI다이버전스 모의숏 {sym} @{px:g} 펌프{price_chg:+.0f}% OI{oi_chg:+.1f}%")
                except Exception: pass
            _save(POS_PATH, positions)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
