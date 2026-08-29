"""
조용한 급등 롱 모의봇 (quietpump_long_paper) — 순수 모의, 매매 API 미호출.

★ 2026-08-26 신설. 사전등록: docs/PREREG_QUIETPUMP_LONG.md (봇 가동 전 작성)

배경: docs/PREREG_SWEEP_BINANCE.md 봉인을 2026-08-26에 단 한 번 열었고, 후보 5개 중
이것 하나가 7개 기준을 전부 통과했다 — 이 프로젝트에서 봉인을 통과한 첫 후보다.
홀드아웃(195종목, 미열람) 건당 +3.522% vs 기준선(무조건 롱) -0.347% = +3.87%p 우위,
부트스트랩 95% CI [+1.09, +5.99], p=0.004, 월별 9/12, n=10,030.

규칙(원본 스윕 bsweep_volume.py:105-110 정의 그대로, 변경 금지):
  신호 = qv/median(qv,288봉) <= 1.2  AND  (종가/12봉전종가 - 1)*100 >= 5.0
        (= 24h 거래대금 중앙값 대비 현재 거래대금 1.2배 이하 "조용" AND 최근 1시간 +5% 이상)
  방향 = 롱 / 보유 = 48시간 고정 / 손절·트레일링 = 없음(백테스트와 조건 일치) / 레버리지 1배

★ 손절이 없는 것은 의도다. 백테스트가 그 조건이었다. 실거래 전환 시 청산 규칙을
  별도 설계·검증해야 하며 그건 이 검정의 대상이 아니다.

★ 내장 대조군: 신호 진입 1건마다 같은 시각에 무작위 코인 1건을 동시 진입한다.
  시장 국면이 통째로 움직여도 짝이 맞는 비교가 되도록 — 백테스트의 기준선에 해당.

★ 순수 모의: 매매 API 미호출. 포트 47260.
상태 data/quietpump_long_pos.json | 기록 data/quietpump_long_trades.csv
로그 logs/quietpump_long_paper.log
Run: python scripts/quietpump_long_paper.py
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
        _sock.bind(("127.0.0.1", 47260))
    except OSError:
        print("[ERROR] quietpump_long_paper 이미 실행 중 (포트 47260)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests
import numpy as np

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [QPUMP] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler("logs/quietpump_long_paper.log", encoding="utf-8")])
log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"

# ── 규칙 상수 (사전등록 1절 — 변경 금지) ────────────────────────────────────
QV_RATIO_MAX = 1.2      # qv / median(qv,288) 상한 = "조용"
R12_MIN = 5.0           # 최근 12봉(1시간) 수익률 하한 %
MED_N = 288             # 거래대금 중앙값 창(24h)
R12_N = 12              # 1시간 = 5분봉 12개
HOLD_H = 24             # 고정 보유
COOLDOWN_H = 12         # 코인당 재진입 쿨다운
LEVERAGE = 1.0          # 명목 기준 기록
FEE_SIDE = 0.0006       # 편도 0.06%(수수료+슬리피지)
MAX_OPEN = 10           # 동시 보유 상한(signal 기준)
POLL_SEC = 300          # 5분

POS_PATH = ROOT / "data" / "quietpump_long_pos.json"
TRADES_PATH = ROOT / "data" / "quietpump_long_trades.csv"
COOLDOWN_PATH = ROOT / "data" / "quietpump_long_cooldown.json"

TRADE_FIELDS = ["entry_time", "exit_time", "symbol", "kind", "entry_price", "exit_price",
                "qv_ratio", "r12_pct", "price_pnl_pct", "funding_pct", "fee_pct",
                "net_pnl_pct", "hold_h", "reason", "btc_entry", "btc_exit", "signal_delay_s",
                "mfe_pct", "mae_pct"]
# ★ 2026-08-30(사용자 지시): 청산규칙 설계를 시작하려면 보유 중 최고/최저가 필요한데
#   지금까지는 진입가·청산가만 기록해 "-41.6%로 끝난 그 거래가 중간에 더 깊이 빠졌다가
#   반등한 건지, 거기가 바닥이었는지" 알 방법이 없었다. 청산 시점에 보유구간 5분봉을
#   통째로 조회해 실제 고가/저가로 계산한다(폴링 스냅샷이 아니라 진짜 캔들 값).
#   기존 30쌍은 소급 불가 — 이 필드는 빈 값으로 남는다(허위로 채우지 않는다).


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
    """바이낸스 USDT 무기한선물 전체."""
    try:
        r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=15)
        return sorted(s["symbol"] for s in r.json()["symbols"]
                      if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
                      and s["symbol"].endswith("USDT"))
    except Exception as e:
        log.warning(f"유니버스 조회 실패: {e}")
        return []


def klines(sym, limit):
    """5분봉. 실패 시 None — 조회실패를 '신호 없음'으로 오판하지 않도록 호출부에서 구분."""
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


def check_signal(sym):
    """원본 스윕(bsweep_volume.py:105-110) 정의 그대로.
    반환 (신호여부, qv비율, r12%, 현재가) — 조회 실패 시 (None, ...)."""
    k = klines(sym, MED_N + 1)
    if k is None:
        return None, None, None, None
    qv = np.array([float(x[7]) for x in k], dtype=float)
    c = np.array([float(x[4]) for x in k], dtype=float)
    med = float(np.median(qv[-(MED_N + 1):-1]))     # 현재봉 제외한 288봉 중앙값
    if not np.isfinite(med) or med <= 0:
        return None, None, None, None
    ratio = float(qv[-1]) / med
    if len(c) < R12_N + 1:
        return None, None, None, None
    r12 = (float(c[-1]) / float(c[-1 - R12_N]) - 1.0) * 100.0
    hit = (ratio <= QV_RATIO_MAX) and (r12 >= R12_MIN)
    return hit, ratio, r12, float(c[-1])


def excursion_pct(sym, entry_px, start_ms, end_ms):
    """보유구간 5분봉 고가/저가로 mfe(최고)·mae(최저) 수익률 계산. 롱 기준(가격 상승=+).
    최대 24h=288봉이라 limit=500 한 번으로 전체 구간을 덮는다. 실패 시 (None, None)
    — 실패를 0으로 채우면 '변동 없었다'로 오독되므로 빈 값으로 남긴다."""
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
        mfe = (hi / entry_px - 1.0) * 100.0
        mae = (lo / entry_px - 1.0) * 100.0
        return round(mfe, 3), round(mae, 3)
    except Exception as e:
        log.warning(f"고저 조회 실패 {sym}: {e}")
        return None, None


def funding_pct(sym, start_ms, end_ms):
    """구간 누적 펀딩률 %. 롱은 양수 펀딩을 **지불**하므로 손익에서 뺀다."""
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
    """기록 실패가 포지션 관리를 막지 않도록 예외를 삼킨다(실거래봇과 동일 패턴)."""
    try:
        new = not TRADES_PATH.exists()
        with open(TRADES_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        log.error(f"기록 실패({e}) — 포지션 정리는 계속: {row.get('symbol')}")


def open_paper(positions, sym, kind, px, ratio, r12, now, btc, delay_s):
    positions[sym + "|" + kind] = {
        "symbol": sym, "kind": kind, "entry_price": px,
        "entry_ts": now, "entry_iso": datetime.now(KST).isoformat(),
        "exit_ts": now + HOLD_H * 3600,
        "qv_ratio": round(ratio, 4) if ratio is not None else None,
        "r12_pct": round(r12, 3) if r12 is not None else None,
        "btc_entry": btc, "signal_delay_s": delay_s,
    }


def main():
    positions = _load(POS_PATH, {})
    cooldown = _load(COOLDOWN_PATH, {})
    now0 = time.time()
    cooldown = {k: v for k, v in cooldown.items() if v > now0}
    rng = random.Random(20260826)
    uni = universe()
    last_uni = time.time()

    log.info(f"조용한급등 롱 모의봇 시작 [🔵모의(dry) — 매매 API 미호출] "
             f"유니버스 {len(uni)}종목 | 신호: qv/med288<={QV_RATIO_MAX} AND 1시간>=+{R12_MIN}% "
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
                net = price_pnl - fnd * LEVERAGE - fee      # 롱은 양수 펀딩 지불
                mfe, mae = excursion_pct(p["symbol"], p["entry_price"],
                                          int(p["entry_ts"] * 1000), int(now * 1000))
                log_trade(dict(
                    entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                    symbol=p["symbol"], kind=p["kind"],
                    entry_price=p["entry_price"], exit_price=px,
                    qv_ratio=p.get("qv_ratio"), r12_pct=p.get("r12_pct"),
                    price_pnl_pct=round(price_pnl, 3), funding_pct=round(fnd, 4),
                    fee_pct=round(fee, 3), net_pnl_pct=round(net, 3),
                    hold_h=round((now - p["entry_ts"]) / 3600, 2), reason=f"{HOLD_H}h만기",
                    btc_entry=p.get("btc_entry"), btc_exit=btc,
                    signal_delay_s=p.get("signal_delay_s"),
                    mfe_pct=mfe, mae_pct=mae))
                log.info(f"[모의청산] {p['symbol']}({p['kind']}) @{px:g} "
                         f"순손익 {net:+.2f}% (가격 {price_pnl:+.2f} 펀딩 -{fnd*LEVERAGE:.2f} 수수료 -{fee:.2f})")
                del positions[key]
            _save(POS_PATH, positions)

            # ── 2) 신호 탐지 ────────────────────────────────────────────────
            n_open = sum(1 for p in positions.values() if p["kind"] == "signal")
            if n_open < MAX_OPEN:
                for sym in uni:
                    if n_open >= MAX_OPEN:
                        break
                    if (sym + "|signal") in positions or cooldown.get(sym, 0) > now:
                        continue
                    t0 = time.time()
                    hit, ratio, r12, px = check_signal(sym)
                    if hit is None:      # 조회 실패 — 신호 없음으로 오판하지 않는다
                        continue
                    if not hit:
                        continue
                    delay = int(time.time() - t0)
                    cooldown[sym] = now + COOLDOWN_H * 3600
                    open_paper(positions, sym, "signal", px, ratio, r12, now, btc, delay)
                    n_open += 1
                    log.info(f"[모의진입:신호] {sym} @{px:g} qv비율 {ratio:.3f} 1시간 {r12:+.2f}%")

                    # ── 대조군: 같은 시각 무작위 코인 1건 (사전등록 2절) ──────
                    cands = [s for s in uni
                             if s != sym and (s + "|random") not in positions
                             and cooldown.get(s, 0) <= now]
                    if cands:
                        rs = rng.choice(cands)
                        rpx = price(rs)
                        if rpx:
                            cooldown[rs] = now + COOLDOWN_H * 3600
                            open_paper(positions, rs, "random", rpx, None, None, now, btc, 0)
                            log.info(f"[모의진입:대조] {rs} @{rpx:g}")
                    _save(POS_PATH, positions)

            cooldown = {k: v for k, v in cooldown.items() if v > time.time()}
            _save(COOLDOWN_PATH, cooldown)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
