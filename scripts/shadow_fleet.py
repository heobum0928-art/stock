"""
그림자 함대 (shadow_fleet) — 순수 모의, 매매 API 미호출. 2026-08-19.

배경: 2026-08-19에 실거래 손익기록의 중대한 결함 3가지가 발견됨.
  ① 펀딩비·수수료가 CSV에 전혀 기록되지 않음 (46건 기간 펀딩비만 -41.08 USDT,
     EV의 약 20%를 잠식하고 있었음)
  ② margin_short_trader가 선물 포지션을 현물(spot) 시세로 감시·기록함
     (all_tickers()가 api.binance.com을 씀 — 체결은 fapi인데). basis 괴리 최대 10.6%.
  ③ 선물전용 상장 코인(527개 중 167개)이 현물 시세조회에서 누락돼 신호의 절반을 못 봄.

이 봇은 그 셋을 전부 바로잡은 조건에서, **하나의 신호 탐지기에 여러 청산/필터 변형을
동시에 물려** 같은 신호에 대한 결과를 짝(paired)으로 비교한다. 서로 다른 시점의 독립
표본을 모으는 것보다 검정력이 훨씬 높다 — 시장 상황이 동일하므로 운의 영향이 상쇄된다.
(2026-08-19 트레일링 반사실 검증이 n=44로도 "판단 불가"였던 것이 이 설계의 동기.)

★ 순수 모의: 주문 API 절대 미호출. 실거래 봇(margin_short_trader)과 완전히 분리됨.
  실거래는 51건 동결검증 중이므로 이 봇의 결과가 그쪽에 영향을 주지 않는다.

변형 목록(전부 같은 신호를 받음 — 진입필터 변형은 일부를 스킵할 뿐):
  V0_base    현행 실거래 규칙 재현 (스탑-40% / 트레일15%p→10%p반납 / 48h만기)
  V1_notrail 트레일링 제거 — 나머지 동일
  V2_hold24  만기 48h→24h — 나머지 동일 (펀딩비 절감 효과 측정)
  V3_fund8h  펀딩주기 8시간 종목만 진입 (4h는 정산이 2배라 비용 2배) — 나머지 V0와 동일
  V4_posfund 진입 직전 펀딩율이 0 이상일 때만 진입 — 나머지 V0와 동일
  V5_stop30  스탑 -40%→-30% — 나머지 동일

손익은 전부 (가격손익 + 펀딩비 + 수수료)로 기록한다. 이게 이 봇의 존재 이유다.

포트 47257. 신호 data/shadow_signals.csv | 거래 data/shadow_trades.csv
상태 data/shadow_fleet_pos.json | 로그 logs/shadow_fleet.log
Run: python scripts/shadow_fleet.py
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
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        _sock.bind(("127.0.0.1", 47257))
    except OSError:
        print("[ERROR] shadow_fleet 이미 실행 중 (포트 47257).")
        sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "data").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [SHADOW] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(ROOT / "logs" / "shadow_fleet.log", encoding="utf-8")])
log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"

# ── 실거래(margin_short_trader)와 동일한 신호 조건 — 비교 가능하게 그대로 ──
LOOKBACK_H   = 7
PUMP_PCT     = 30.0
PUMP_PCT_MAX = 40.0
MIN_QUOTE_VOL = 3_000_000
PRESCREEN_24H = 5.0
STOP_PCT          = 40.0
TRAIL_TRIGGER_PCT = 15.0
TRAIL_GIVEBACK_PCT = 10.0
HOLD_H       = 48
COOLDOWN_H   = 12   # 실거래와 동일 — 같은 코인 재신호 억제(중복기록 방지 겸용)

NOTIONAL_USDT = 60.0   # 실거래와 동일(증거금30 × 레버2). 순수 명목, 실제 자금 아님
MARGIN_USDT   = 30.0   # 증거금 대비 % 계산용
TAKER_FEE     = 0.0005 # 왕복 계산 시 ×2

POLL_SEC = 180
UNIVERSE_REFRESH_H = 6

POS_PATH     = ROOT / "data" / "shadow_fleet_pos.json"
SIGNALS_PATH = ROOT / "data" / "shadow_signals.csv"
TRADES_PATH  = ROOT / "data" / "shadow_trades.csv"
FUNDINFO_PATH = ROOT / "data" / "_shadow_funding_interval.json"
SIGCD_PATH    = ROOT / "data" / "shadow_sig_cooldown.json"

# ── 변형 정의 ──
# entry_filter(sig) -> bool (진입할지) / 나머지는 청산 파라미터
VARIANTS = {
    "V0_base":    dict(stop=40.0, trail=(15.0, 10.0), hold_h=48, filt=None),
    "V1_notrail": dict(stop=40.0, trail=None,          hold_h=48, filt=None),
    "V2_hold24":  dict(stop=40.0, trail=(15.0, 10.0), hold_h=24, filt=None),
    "V3_fund8h":  dict(stop=40.0, trail=(15.0, 10.0), hold_h=48, filt="funding_8h_only"),
    "V4_posfund": dict(stop=40.0, trail=(15.0, 10.0), hold_h=48, filt="funding_non_negative"),
    "V5_stop30":  dict(stop=30.0, trail=(15.0, 10.0), hold_h=48, filt=None),
}


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, o):
    tmp = Path(p).with_suffix(".tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _get(path, params=None, timeout=10):
    r = requests.get(f"{FAPI}{path}", params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def futures_universe():
    """선물 무기한 USDT 페어 전체 — 현물 상장 여부와 무관(사각지대 버그 수정분)."""
    info = _get("/fapi/v1/exchangeInfo", timeout=20)
    return [s["symbol"] for s in info["symbols"]
            if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
            and s["symbol"].endswith("USDT")]


def funding_intervals():
    """심볼별 펀딩 정산주기(시간). 2026-08-19 발견: 상당수가 8h가 아니라 4h/1h이고,
    1h 주기 종목이 전체 펀딩비의 45%를 냈다. 캐시해두고 6시간마다 갱신."""
    cache = _load(FUNDINFO_PATH, {})
    if cache and time.time() - cache.get("_ts", 0) < UNIVERSE_REFRESH_H * 3600:
        return cache
    out = {"_ts": time.time()}
    try:
        for x in _get("/fapi/v1/fundingInfo", timeout=15):
            try:
                out[x["symbol"]] = float(x.get("fundingIntervalHours", 8))
            except Exception:
                pass
    except Exception as e:
        log.warning(f"fundingInfo 조회 실패({e}) — 기존 캐시 사용")
        return cache or {"_ts": time.time()}
    _save(FUNDINFO_PATH, out)
    return out


def last_funding_rate(sym):
    """진입 직전 펀딩율. 2026-08-19 발견: 이 값과 실제 펀딩 부담의 Spearman 상관 +0.668,
    음수였던 건들이 전체 펀딩비의 94%를 냈다 → V4 변형의 진입 필터 근거."""
    try:
        r = _get("/fapi/v1/fundingRate", {"symbol": sym, "limit": 1})
        return float(r[-1]["fundingRate"]) if r else None
    except Exception:
        return None


def funding_paid(sym, start_ms, end_ms, notional):
    """보유구간 실제 펀딩비. 숏이므로 펀딩율이 양수면 받고(+), 음수면 낸다(-).
    명목은 진입명목 고정 근사(원장 대조 시 오차 약 7%, 마크 재평가 대비 보수적)."""
    try:
        rows = _get("/fapi/v1/fundingRate",
                    {"symbol": sym, "startTime": int(start_ms), "endTime": int(end_ms), "limit": 1000})
    except Exception as e:
        log.warning(f"[{sym}] 펀딩조회 실패: {e} — 0으로 기록(과소추정 주의)")
        return 0.0, 0
    tot = sum(float(x["fundingRate"]) for x in rows)
    return notional * tot, len(rows)


def pump_pct(sym):
    """LOOKBACK_H시간 상승률 — 선물 5분봉 기준(실거래는 현물을 쓰는 버그가 있음)."""
    n = LOOKBACK_H * 12
    try:
        kl = _get("/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": n + 1})
    except Exception:
        return None, 0.0
    if len(kl) < n + 1:
        return None, 0.0
    old, now = float(kl[0][1]), float(kl[-1][4])
    if old <= 0:
        return None, 0.0
    return (now / old - 1) * 100, now


SIG_FIELDS = ["signal_id", "time", "symbol", "pump_pct", "price", "qvol_24h",
              "chg_24h", "funding_rate", "funding_interval_h", "taken_by", "skipped_by"]
TRADE_FIELDS = ["signal_id", "variant", "symbol", "entry_time", "exit_time",
                "entry_price", "exit_price", "hold_h", "reason",
                "price_pnl_pct", "price_pnl_usdt", "funding_usdt", "funding_events",
                "commission_usdt", "net_pnl_usdt", "net_pnl_pct_margin",
                "mfe_pct", "mae_pct", "funding_rate_at_entry", "funding_interval_h"]


def _append(path, fields, row):
    new = not Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def entry_allowed(filt, sig):
    if filt is None:
        return True
    if filt == "funding_8h_only":
        # 2026-08-19 실측: 선물 전종목 중 8h주기 314개 / 4h주기 445개 / 1h 1개(COTI).
        # 4h는 8h 대비 정산이 2배라 같은 보유시간에 펀딩비를 2배 낸다. 8h만 골랐을 때
        # 비용 절감이 신호 수 감소(약 40%)를 상쇄하는지 보는 변형.
        return (sig.get("funding_interval_h") or 8) >= 8
    if filt == "funding_non_negative":
        fr = sig.get("funding_rate")
        return fr is not None and fr >= 0
    return True


def main():
    positions = _load(POS_PATH, {})          # {variant: {symbol: pos}}
    for v in VARIANTS:
        positions.setdefault(v, {})
    sig_cooldown = {k: v for k, v in _load(SIGCD_PATH, {}).items() if v > time.time()}
    universe, last_uni = [], 0.0
    finfo = {}
    log.info(f"그림자 함대 시작 — 변형 {len(VARIANTS)}개 {list(VARIANTS)} | "
             f"선물 전종목 스캔(사각지대 포함) | 펀딩비·수수료 반영 | 순수모의(매매0)")
    try:
        from bithumb import notify
        notify.send(f"🛰 그림자 함대 시작 — {len(VARIANTS)}개 변형 병렬 검증(순수모의, 실주문 없음)")
    except Exception:
        pass

    while True:
        try:
            now = time.time()
            if now - last_uni >= UNIVERSE_REFRESH_H * 3600 or not universe:
                try:
                    universe = futures_universe()
                    finfo = funding_intervals()
                    last_uni = now
                    log.info(f"유니버스 갱신: {len(universe)}개 | 펀딩주기 정보 {len(finfo)-1}개")
                except Exception as e:
                    log.error(f"유니버스 갱신 실패: {e}")
                    if not universe:
                        time.sleep(60); continue

            tick = {}
            try:
                for d in _get("/fapi/v1/ticker/24hr", timeout=20):
                    tick[d["symbol"]] = (float(d["lastPrice"]), float(d["priceChangePercent"]),
                                         float(d["quoteVolume"]))
            except Exception as e:
                log.error(f"티커 조회 실패: {e}")
                time.sleep(30); continue

            # ── 1) 청산 점검 (변형별) ──
            for vname, cfg in VARIANTS.items():
                for sym in list(positions[vname].keys()):
                    p = positions[vname][sym]
                    t = tick.get(sym)
                    if not t:
                        continue
                    px = t[0]
                    p["mfe_price"] = min(p.get("mfe_price", px), px)   # 숏: 하락이 유리
                    p["mae_price"] = max(p.get("mae_price", px), px)
                    entry = p["entry_price"]
                    cur_pnl = (1 - px / entry) * 100
                    peak_pnl = (1 - p["mfe_price"] / entry) * 100
                    hold_h = (now - p["entry_ts"]) / 3600

                    reason = None
                    if px >= entry * (1 + cfg["stop"] / 100):
                        reason = f"스탑-{cfg['stop']:.0f}%"
                    elif cfg["trail"]:
                        trig, give = cfg["trail"]
                        if peak_pnl >= trig and cur_pnl <= peak_pnl - give:
                            reason = f"트레일링(최고{peak_pnl:.0f}%→{cur_pnl:.0f}%)"
                    if reason is None and hold_h >= cfg["hold_h"]:
                        reason = f"{cfg['hold_h']}h만기"
                    if not reason:
                        continue

                    fund, fev = funding_paid(sym, p["entry_ms"], now * 1000, NOTIONAL_USDT)
                    comm = -NOTIONAL_USDT * TAKER_FEE * 2
                    price_pnl_usdt = NOTIONAL_USDT * cur_pnl / 100
                    net = price_pnl_usdt + fund + comm

                    del positions[vname][sym]
                    _save(POS_PATH, positions)
                    _append(TRADES_PATH, TRADE_FIELDS, dict(
                        signal_id=p["signal_id"], variant=vname, symbol=sym,
                        entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                        entry_price=entry, exit_price=px, hold_h=round(hold_h, 2), reason=reason,
                        price_pnl_pct=round(cur_pnl, 2), price_pnl_usdt=round(price_pnl_usdt, 3),
                        funding_usdt=round(fund, 4), funding_events=fev,
                        commission_usdt=round(comm, 4), net_pnl_usdt=round(net, 3),
                        net_pnl_pct_margin=round(net / MARGIN_USDT * 100, 2),
                        mfe_pct=round(peak_pnl, 2),
                        mae_pct=round((p["mae_price"] / entry - 1) * 100, 2),
                        funding_rate_at_entry=p.get("funding_rate"),
                        funding_interval_h=p.get("funding_interval_h")))
                    log.info(f"[{vname}] 청산 {sym} {reason} 가격{cur_pnl:+.1f}% "
                             f"펀딩{fund:+.2f} 순{net:+.2f}U")

            # ── 2) 신호 탐지 → 변형별 진입 ──
            # ★ 2026-08-19 수정: 급등 조건은 몇 시간씩 유지되므로, 쿨다운 없이 두면 같은
            # 심볼의 신호가 폴링마다 반복 기록된다(STARUSDT가 6회 중복 기록됨). 실거래
            # margin_short_trader도 COOLDOWN_H=12로 같은 코인 재진입을 막으므로 동일하게 적용.
            # 신호 자체를 쿨다운 안에서는 아예 발생시키지 않아 중복 기록도 함께 막는다.
            for sym in universe:
                if sig_cooldown.get(sym, 0) > now:
                    continue
                t = tick.get(sym)
                if not t:
                    continue
                px0, chg24, qvol = t
                if px0 <= 0 or qvol < MIN_QUOTE_VOL or chg24 < PRESCREEN_24H:
                    continue
                ret, px = pump_pct(sym)
                if ret is None or ret < PUMP_PCT or ret >= PUMP_PCT_MAX:
                    continue

                sig_id = f"{datetime.now(KST).strftime('%m%d%H%M%S')}-{sym}"
                sig = dict(signal_id=sig_id, time=datetime.now(KST).isoformat(), symbol=sym,
                           pump_pct=round(ret, 2), price=px, qvol_24h=round(qvol),
                           chg_24h=round(chg24, 2),
                           funding_rate=last_funding_rate(sym),
                           funding_interval_h=finfo.get(sym, 8))
                taken, skipped = [], []
                for vname, cfg in VARIANTS.items():
                    if sym in positions[vname]:
                        skipped.append(f"{vname}:보유중"); continue
                    if not entry_allowed(cfg["filt"], sig):
                        skipped.append(f"{vname}:{cfg['filt']}"); continue
                    positions[vname][sym] = dict(
                        signal_id=sig_id, entry_price=px, entry_ts=now, entry_ms=now * 1000,
                        entry_iso=datetime.now(KST).isoformat(),
                        mfe_price=px, mae_price=px,
                        funding_rate=sig["funding_rate"],
                        funding_interval_h=sig["funding_interval_h"])
                    taken.append(vname)
                sig["taken_by"] = "|".join(taken)
                sig["skipped_by"] = "|".join(skipped)
                sig_cooldown[sym] = now + COOLDOWN_H * 3600
                _save(SIGCD_PATH, sig_cooldown)
                _append(SIGNALS_PATH, SIG_FIELDS, sig)
                if taken:
                    _save(POS_PATH, positions)
                log.warning(f"[신호] {sym} 7h+{ret:.1f}% 펀딩율{sig['funding_rate']} "
                            f"주기{sig['funding_interval_h']}h → 진입 {len(taken)}/{len(VARIANTS)}개 변형")
                time.sleep(0.2)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
