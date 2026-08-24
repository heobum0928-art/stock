"""
교차거래소 숏 모의검증기 (crossex_short_paper) — 순수 모의, 매매 API 미호출.

배경(2026-08-24): 같은 규칙의 부호가 시장에 따라 뒤집힌다는 것을 확인했다.
  "4h 저점 대비 +50% 급등 → 24h 숏"
    · 업비트 원화 현물  : +17.92% (승률 82.8%, 봉인 검증 통과)
    · 바이낸스 USDT 선물: -16.56% (승률 45.4%)
  메커니즘 가설(2026-08-20 crossex 분석과 일치): 한국 시장은 후행(lead 80.7%).
  바이낸스에서 +50%는 상승 초반이고, 업비트에서 +50%는 끝물이다.
  막힌 것은 실행 — 업비트는 현물이라 숏이 불가능하다.
  → 신호원과 실행처를 분리한다: 업비트에서 보고, 바이낸스에서 판다.

★ 이 가설은 백테스트로 검증된 적이 없다. 두 결과를 잇는 추론이다. 그래서 모의로 시작한다.
★ 사전등록: docs/PREREG_CROSSEX_SHORT.md — 규칙·판정기준이 거기 고정돼 있다.

내장 대조군: 신호 진입 1건마다 같은 시각에 무작위 코인 1건을 동시 모의 진입한다.
  시장이 통째로 오르내려도 짝이 맞는 비교가 되도록 — 레짐 착시를 구조적으로 막는다.

★ 순수 모의: 매매 API 미호출. 포트 47257.
기록 data/crossex_short_trades.csv | 상태 data/crossex_short_pos.json
로그 logs/crossex_short_paper.log
Run: python scripts/crossex_short_paper.py
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
        _sock.bind(("127.0.0.1", 47257))
    except OSError:
        print("[ERROR] crossex_short_paper 이미 실행 중 (포트 47257).")
        sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [XSHORT] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler("logs/crossex_short_paper.log", encoding="utf-8")])
log = logging.getLogger(__name__)

UPBIT = "https://api.upbit.com"
FAPI = "https://fapi.binance.com"
POS_PATH = ROOT / "data" / "crossex_short_pos.json"
TRADES_PATH = ROOT / "data" / "crossex_short_trades.csv"
UNIV_PATH = ROOT / "data" / "crossex_short_universe.json"

# ── 사전등록된 규칙 (docs/PREREG_CROSSEX_SHORT.md) — 결과를 보고 바꾸지 않는다 ──
LOOKBACK_BARS = 48        # 4시간 (5분봉 48개)
DU_THRESHOLD = 50.0       # 저점 대비 +50% 급등
HOLD_H = 24               # 24시간 고정 보유
COOLDOWN_H = 12           # 코인별 쿨다운
COST_SIDE = 0.0006        # 편도 0.06% (수수료+슬리피지)
LEV = 1.0                 # 명목 기준 기록
POLL_SEC = 300            # 5분
UNIV_REFRESH_H = 12
MIN_UPBIT_QV_24H = 1e8    # 업비트 24h 거래대금 1억원 하한 (호가 튐 방어)

CSV_COLS = ["entry_time", "exit_time", "coin", "kind", "du_pct",
            "up_entry", "up_exit", "bn_entry", "bn_exit",
            "gap_entry_pct", "price_pnl_pct", "funding_pct", "fee_pct", "net_pnl_pct",
            "signal_delay_sec", "hold_h", "btc_entry", "btc_exit"]


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, o):
    tmp = Path(p).with_suffix(".tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def log_trade(row):
    new = not TRADES_PATH.exists()
    with open(TRADES_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in CSV_COLS})


def build_universe():
    """업비트 원화 ∩ 바이낸스 USDT 무기한선물. 12시간마다 갱신."""
    up = requests.get(f"{UPBIT}/v1/market/all", timeout=10).json()
    ukrw = set(m["market"].split("-")[1] for m in up if m["market"].startswith("KRW-"))
    bn = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=10).json()
    bperp = set(s["baseAsset"] for s in bn["symbols"]
                if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT")
    inter = sorted(ukrw & bperp)
    _save(UNIV_PATH, {"ts": time.time(), "coins": inter})
    log.info(f"유니버스 갱신: 업비트원화 {len(ukrw)} ∩ 바이낸스퍼프 {len(bperp)} = {len(inter)}종목")
    return inter


def upbit_candles(coin, count=LOOKBACK_BARS + 2):
    """업비트 5분봉. 실패 시 None."""
    try:
        r = requests.get(f"{UPBIT}/v1/candles/minutes/5",
                         params={"market": f"KRW-{coin}", "count": count}, timeout=8)
        if r.status_code != 200:
            return None
        c = r.json()
        return c if isinstance(c, list) and len(c) >= LOOKBACK_BARS else None
    except Exception:
        return None


def binance_prices():
    """바이낸스 선물 전 종목 현재가 {BASEUSDT: price}."""
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/price", timeout=10)
        return {x["symbol"]: float(x["price"]) for x in r.json()}
    except Exception as e:
        log.warning(f"바이낸스 시세 조회 실패: {e}")
        return {}


def funding_between(sym, t0_ms, t1_ms):
    """진입~청산 사이 실현 펀딩률 합(%). 숏은 양수 펀딩을 수취하므로 그대로 더한다."""
    try:
        r = requests.get(f"{FAPI}/fapi/v1/fundingRate",
                         params={"symbol": sym, "startTime": int(t0_ms),
                                 "endTime": int(t1_ms), "limit": 100}, timeout=8)
        if r.status_code != 200:
            return 0.0
        return sum(float(x["fundingRate"]) for x in r.json()) * 100.0
    except Exception:
        return 0.0


def du_pct(candles):
    """DU_48 = (현재 종가 / 최근 48봉 저가최소 - 1) * 100. 업비트는 최신봉이 [0]."""
    win = candles[:LOOKBACK_BARS]
    lo = min(float(c["low_price"]) for c in win)
    cur = float(win[0]["trade_price"])
    if lo <= 0:
        return None, None, None
    qv24 = sum(float(c.get("candle_acc_trade_price", 0)) for c in candles[:min(len(candles), 288)])
    return (cur / lo - 1.0) * 100.0, cur, qv24


def open_paper(positions, coin, kind, du, up_px, bn_px, now, delay, btc):
    positions[f"{coin}|{kind}"] = {
        "coin": coin, "kind": kind, "du_pct": round(du, 2) if du is not None else None,
        "entry_ts": now, "exit_ts": now + HOLD_H * 3600,
        "entry_iso": datetime.now(KST).isoformat(),
        "up_entry": up_px, "bn_entry": bn_px,
        "signal_delay_sec": round(delay, 1), "btc_entry": btc,
    }


def main():
    positions = _load(POS_PATH, {})
    cooldown = {}
    universe = _load(UNIV_PATH, {}).get("coins") or build_universe()
    univ_ts = _load(UNIV_PATH, {}).get("ts", 0)
    rng = random.Random(20260824)
    log.info(f"교차거래소 숏 모의검증기 시작 [모의] — 유니버스 {len(universe)}종목 | "
             f"업비트 DU_{LOOKBACK_BARS}봉>+{DU_THRESHOLD:.0f}% → 바이낸스 {HOLD_H}h 숏 | "
             f"신호 1건마다 무작위 대조군 1건 동시 진입")

    while True:
        try:
            now = time.time()
            if now - univ_ts > UNIV_REFRESH_H * 3600:
                universe = build_universe()
                univ_ts = now

            bn = binance_prices()
            btc = bn.get("BTCUSDT")

            # ── 1) 청산 점검 (루프 맨 앞 — 만기 지연 방지) ──
            for key in list(positions.keys()):
                p = positions[key]
                if now < p["exit_ts"]:
                    continue
                sym = f"{p['coin']}USDT"
                bx = bn.get(sym)
                if bx is None:
                    log.warning(f"청산 보류 {key}: 바이낸스 시세 없음, 다음 루프 재시도")
                    continue
                cd = upbit_candles(p["coin"], count=2)
                ux = float(cd[0]["trade_price"]) if cd else None
                price_pnl = -(bx / p["bn_entry"] - 1.0) * 100.0 * LEV          # 숏
                fund = funding_between(sym, p["entry_ts"] * 1000, now * 1000) * LEV
                fee = -COST_SIDE * 2 * 100.0 * LEV
                net = price_pnl + fund + fee
                gap = ((p["bn_entry"] / p["up_entry"] - 1.0) * 100.0
                       if p.get("up_entry") else None)
                log_trade(dict(
                    entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                    coin=p["coin"], kind=p["kind"], du_pct=p.get("du_pct"),
                    up_entry=p.get("up_entry"), up_exit=ux,
                    bn_entry=p["bn_entry"], bn_exit=bx,
                    gap_entry_pct=round(gap, 4) if gap is not None else None,
                    price_pnl_pct=round(price_pnl, 3), funding_pct=round(fund, 4),
                    fee_pct=round(fee, 3), net_pnl_pct=round(net, 3),
                    signal_delay_sec=p.get("signal_delay_sec"),
                    hold_h=round((now - p["entry_ts"]) / 3600, 2),
                    btc_entry=p.get("btc_entry"), btc_exit=btc))
                log.info(f"[청산:{p['kind']}] {p['coin']} 가격{price_pnl:+.2f}% "
                         f"펀딩{fund:+.3f}% 수수료{fee:+.2f}% → 순{net:+.2f}%")
                del positions[key]
            _save(POS_PATH, positions)

            # ── 2) 신호 탐지 ──
            fired = []
            for coin in universe:
                if f"{coin}|signal" in positions:
                    continue
                if now < cooldown.get(coin, 0):
                    continue
                sym = f"{coin}USDT"
                if sym not in bn:
                    continue
                cd = upbit_candles(coin)
                if not cd:
                    continue
                du, up_px, qv24 = du_pct(cd)
                if du is None or du < DU_THRESHOLD:
                    continue
                if qv24 is not None and qv24 < MIN_UPBIT_QV_24H:
                    log.info(f"신호 스킵(유동성) {coin} DU={du:.1f}% 24h거래대금 {qv24/1e8:.2f}억")
                    continue
                # 업비트 최신봉 종료시각 → 지금까지의 지연
                try:
                    kst_s = cd[0]["candle_date_time_kst"]
                    bar_ts = datetime.fromisoformat(kst_s).replace(tzinfo=KST).timestamp()
                    delay = now - (bar_ts + 300)
                except Exception:
                    delay = 0.0
                fired.append((coin, du, up_px, bn[sym], max(delay, 0.0)))
                time.sleep(0.12)      # 업비트 레이트리밋 여유

            # ── 3) 진입: 신호 1건마다 무작위 대조군 1건 동시 진입 ──
            for coin, du, up_px, bn_px, delay in fired:
                open_paper(positions, coin, "signal", du, up_px, bn_px, now, delay, btc)
                cooldown[coin] = now + COOLDOWN_H * 3600
                log.info(f"[진입:signal] {coin} DU={du:.1f}% 업비트{up_px:g} 바이낸스{bn_px:g} "
                         f"지연{delay:.0f}s")
                # 대조군 — 같은 시각, 유니버스에서 균등 추출
                cands = [c for c in universe
                         if f"{c}|random" not in positions and f"{c}USDT" in bn
                         and now >= cooldown.get(f"__rand_{c}", 0)]
                if cands:
                    rc = rng.choice(cands)
                    rcd = upbit_candles(rc, count=2)
                    rup = float(rcd[0]["trade_price"]) if rcd else None
                    open_paper(positions, rc, "random", None, rup, bn[f"{rc}USDT"], now, 0.0, btc)
                    cooldown[f"__rand_{rc}"] = now + COOLDOWN_H * 3600
                    log.info(f"[진입:random] {rc} (대조군) 바이낸스{bn[f'{rc}USDT']:g}")
            if fired:
                _save(POS_PATH, positions)

            if not fired:
                log.info(f"신호 없음 — 보유 {len(positions)}건")

        except Exception as e:
            log.error(f"루프 예외(계속 진행): {e}", exc_info=True)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
