"""
🔴 실거래 — 레버리지 코어 — BTC 200일선 타이밍 + 2배 레버리지 (바이낸스 무기한선물).

★★ 2026-08-20 라벨 정정: 아래 원문에 "100% 모의, 절대 이 상태로 실거래 안 나감"이라고
   적혀 있으나 **사실이 아니다.** data/binance_live_config.json의 armed_engines에
   "core_lev"가 들어 있어 실주문이 나가는 상태이고, 2026-08-20 08:43:54에 실제
   MARKET BUY 0.001 BTC가 체결됐다(data/binance_orders.csv 기록). 감사에서 발견됨.
   원문은 이력 보존을 위해 아래에 그대로 두되, 이 파일을 여는 사람이 "모의니까
   괜찮다"고 오판하지 않도록 여기에 먼저 명시한다.

   ⚠️ 이 경로에는 **서버측 손절(STOP_MARKET)이 없다.** margin_short(선물폴백)는
   진입 직후 거래소에 스탑을 걸지만 rebalance_long()에는 그 코드가 없다. 즉 봇이
   죽어 있는 동안 BTC가 급락하면 보호 장치가 없다. 청산위험 70% 경보는 2026-08-20에
   실전 경로에도 추가했으나(그 전엔 모의 경로에만 있었음), 그건 알림이지 손절이 아니다.

배경(2026-07-09): 유일하게 검증된 엣지(BTC/ETH 200일선, +34.8% vs HODL -1.2%)에
레버리지를 얹어 배수를 키우자는 결정. 빗썸은 레버리지 미지원 → 바이낸스 BTCUSDT
무기한선물 시세로 모의 추적. 신호는 core_trader.py와 100% 동일(SMA50/200, 1%밴드).

★ 안전 레버리지 산출 근거 (800일 데이터, 보유구간 6개 중 최악):
  2024-11-17~2025-03-09(113일) 보유 중 -24.1% 낙폭이 관측 최악치.
  표본 6개뿐이라(과거 미관측 -50%급 폭락 가능성 배제 못 함) 레버리지 2배로 제한
  — 2배면 과거 최악치(-24%)의 2배(-48%)까지 버팀, 그 이상(-50%대)에서는 청산 위험.
  3배 이상은 과거 최악치만으로도 청산에 근접해 채택 안 함.

포지션 로직: FULL(200일선 위)=자본 100% 증거금×2배 레버리지(명목노출 200%),
SCOUT(50일선 위)=자본 30%×2배(명목노출 60%), 둘 다 아래=CASH.
청산위험 경보: 미실현손실이 증거금의 70% 도달 시 CRITICAL 알림(청산선 근접).
펀딩비: 바이낸스 실시간 펀딩레이트를 8시간마다 정산 반영.

⚠️ [원문 — 2026-07-09 작성 당시 기준, 지금은 사실 아님. 위 라벨 정정 참조]
   "현재 100% 모의(노셔널). 바이낸스 API 키 연동 전까지 실주문 불가능 — 계좌·키
   준비되면 별도로 live_guard 스타일 실행가드 추가 예정. 절대 이 상태로 실거래 안 나감."
   → 그 뒤 실제로 가드가 붙고 armed 되면서 실거래로 전환됐는데 이 문장이 갱신되지 않았다.
상태: data/core_leveraged_state.json | 로그: logs/core_leveraged.log
Run: python scripts/core_leveraged.py
"""
import sys, os, atexit, time, json, socket, logging
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
    try: _sock.bind(("127.0.0.1", 47249))
    except OSError: print("[ERROR] core_leveraged 이미 실행 중 (포트 47249)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests
from bithumb import notify
from bithumb.binance_guard import BinanceGuard, live_status as bn_live_status, get_futures_usdt, get_position

ENGINE = "core_lev"

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [CORE-LEV] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/core_leveraged.log", encoding="utf-8")])
log = logging.getLogger(__name__)

LEVERAGE = 2.0
NOTIONAL_KRW = 1_000_000     # 모의 노셔널 자본 (core_trader.py와 동일선상 비교용)
SCOUT_FRAC, FULL_FRAC = 0.30, 1.0
SMA_FAST, SMA_SLOW = 50, 200
BAND = 0.01
COST = 0.0004                # 바이낸스 선물 테이커 0.04%/사이드 근사
LIQ_WARN_FRAC = 0.70         # 증거금의 70% 손실 시 경보
CHECK_SEC = 1800             # 30분 (일봉 신호라 충분, funding은 별도 8h 정산)
FUNDING_INTERVAL_SEC = 8 * 3600

BTC_FILE = ROOT / "data" / "candles_daily" / "BTC_1d.json"
STATE = ROOT / "data" / "core_leveraged_state.json"
FAPI = "https://fapi.binance.com"


def sma_signal():
    """일봉 BTC(빗썸 KRW 기준)로 SMA50/200 신호 계산 — core_trader.py와 동일 신호."""
    try:
        cl = [float(x["trade_price"]) for x in json.loads(BTC_FILE.read_text(encoding="utf-8"))]
        if len(cl) < SMA_SLOW: return None
        cur = cl[-1]; s50 = sum(cl[-SMA_FAST:]) / SMA_FAST; s200 = sum(cl[-SMA_SLOW:]) / SMA_SLOW
        return cur > s50 * (1 + BAND), cur > s200 * (1 + BAND)
    except Exception as e:
        log.warning(f"신호 조회 실패: {e}"); return None


def binance_price() -> float:
    r = requests.get(f"{FAPI}/fapi/v1/ticker/price", params={"symbol": "BTCUSDT"}, timeout=8)
    r.raise_for_status()
    return float(r.json()["price"])


def binance_funding_rate() -> float:
    """가장 최근 실현 펀딩레이트(비율, 8시간당)."""
    r = requests.get(f"{FAPI}/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"}, timeout=8)
    r.raise_for_status()
    return float(r.json().get("lastFundingRate", 0) or 0)


def load_state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception: pass
    return {"state": "CASH", "equity": float(NOTIONAL_KRW), "margin_frac": 0.0,
            "entry_price": 0.0, "last_price": 0.0, "last_funding_ts": 0.0}


def save_state(s):
    tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(s, indent=2), encoding="utf-8"); os.replace(tmp, STATE)


def mark_to_market(s, price):
    """가격 변동을 레버리지 배율만큼 증거금에 반영. margin_frac=0이면 변화없음(현금)."""
    if s["margin_frac"] <= 0 or s["last_price"] <= 0:
        s["last_price"] = price
        return
    price_ret = price / s["last_price"] - 1
    notional_frac = s["margin_frac"] * LEVERAGE
    pnl = s["equity"] * notional_frac * price_ret
    s["equity"] += pnl
    s["last_price"] = price

    margin_krw = s["equity"] * s["margin_frac"]  # 근사(엄밀히는 진입시점 증거금 기준이나 단순화)
    unrealized_from_entry = (price / s["entry_price"] - 1) if s["entry_price"] > 0 else 0
    loss_frac_of_margin = -unrealized_from_entry * LEVERAGE  # 양수면 손실중
    if loss_frac_of_margin >= LIQ_WARN_FRAC:
        # ★ 모의(paper) 경로 전용 — 실제 포지션이 아니므로 텔레그램 알림은 생략, 로그만 (실전에서만 알림 원칙)
        msg = (f"🚨 청산위험 경보(모의) — 증거금의 {loss_frac_of_margin*100:.0f}% 손실 "
               f"(진입가 {s['entry_price']:,.0f} → 현재 {price:,.0f}, {unrealized_from_entry*100:+.1f}%)")
        log.error(msg)


def apply_funding(s, price):
    now = time.time()
    if s["margin_frac"] <= 0:
        s["last_funding_ts"] = now
        return
    if s["last_funding_ts"] <= 0:
        s["last_funding_ts"] = now
        return
    if now - s["last_funding_ts"] < FUNDING_INTERVAL_SEC:
        return
    try:
        rate = binance_funding_rate()
    except Exception as e:
        log.warning(f"펀딩레이트 조회 실패: {e}"); return
    notional_frac = s["margin_frac"] * LEVERAGE
    cost = s["equity"] * notional_frac * rate  # 롱이 펀딩 지불(+rate) 또는 수취(-rate)
    s["equity"] -= cost
    s["last_funding_ts"] = now
    log.info(f"펀딩 정산 rate={rate*100:+.4f}% notional_frac={notional_frac:.2f} → {-cost:+,.0f}원")


def rebalance(s, target_frac, price, reason):
    old_frac = s["margin_frac"]
    if target_frac == old_frac:
        return False
    cost_krw = s["equity"] * abs(target_frac - old_frac) * LEVERAGE * COST
    s["equity"] -= cost_krw
    s["margin_frac"] = target_frac
    s["entry_price"] = price if target_frac > 0 else 0.0
    s["last_price"] = price
    log.warning(f"리밸런싱(모의) → {reason}: 증거금비중 {target_frac*100:.0f}%(명목노출 {target_frac*LEVERAGE*100:.0f}%) "
                f"@{price:,.2f} 비용{-cost_krw:,.0f}원 | 모의자산 {s['equity']:,.0f}원 "
                f"({(s['equity']/NOTIONAL_KRW-1)*100:+.1f}%)")
    # ★ 모의 리밸런싱은 실거래가 아니므로 텔레그램 알림 생략 (실전에서만 알림 원칙, 로그로만 확인)
    return True


def live_target_notional(target_frac):
    """목표 명목노출(USDT). 실패 시 None. live_rebalance()와 동일 공식을 공유해
    '유지' 분기의 실포지션 대조에서도 같은 기준을 쓰게 한다(2026-09-02 신설)."""
    from bithumb.binance_guard import load_config
    usdt = get_futures_usdt()
    if usdt is None or usdt <= 0:
        return None
    cap = load_config().get("engine_caps_usdt", {}).get(ENGINE, 0)
    return min(usdt, cap) * target_frac * LEVERAGE


# ★ 2026-09-02(버그감사 지적, 사용자 승인 후 수정): '유지' 분기 실포지션 대조 허용오차.
#   목표의 15% 또는 10 USDT 중 큰 값을 넘게 벌어져야 교정한다 — rebalance_long()의
#   자체 스킵 문턱(5 USDT)보다 넉넉히 크게 잡아 매 사이클 진동하지 않게 한다.
DRIFT_TOL_FRAC = 0.15
DRIFT_TOL_USDT = 10.0
# ★★ 2026-09-02 당일 재수정(버그헌터 B1): 위 허용오차만으로는 **도달 불가능한 목표를
#   30분마다 영원히 재시도**한다. rebalance_long()은 BTC 수량을 0.001 단위로 반올림하는데
#   (binance_guard.py의 `round(delta/price, 3)`), BTC 77,000 기준 0.001 = 약 77 USDT다.
#   즉 최소 조정 단위(77)가 허용오차(30)보다 크므로 목표에 절대 수렴할 수 없다.
#   실제 발생: 목표 200 → 0.003BTC(231.7) 체결 → 차 31.7 > 30 → 교정 시도 → delta 31.7이
#   0.0004BTC로 반올림되어 0 → skip → 30분 뒤 반복(7회 확인, 🚨 알림도 매번 발송).
#   → 최소 주문 격자보다 확실히 큰 값을 함께 요구한다. 격자 안에서는 더 못 맞추는 게 정상.
MIN_QTY_STEP_BTC = 0.001      # binance_guard.rebalance_long()의 round(,3)과 일치
DRIFT_STEP_MULT = 1.5         # 격자의 1.5배는 벌어져야 실제로 조정 가능


def live_rebalance(guard, target_frac, price):
    """실전 모드 — 목표 명목노출까지 가드 통해 실주문.
    증거금 = min(선물잔고, 엔진상한) × target_frac. 명목 = 증거금 × LEVERAGE.
    ★ 잔고가 상한보다 커도 상한만큼만 사용(소액검증 안전) — 상한이 진입을 막지 않고 규모만 제한.
    ★ 2026-08-15(버그헌터 발견): 반환값이 성공(live/skip=이미 목표달성)인지 실패(dry/error)인지
    구분해 반환 — 호출부가 실패 시 로컬 state 저장을 건너뛰고 다음 루프에서 재시도하게 함.
    이전엔 호출 성공여부와 무관하게 항상 state를 갱신해서, 캡차단·API실패 시 "청산했다고
    착각하고 실제로는 포지션이 거래소에 남아있는" 영구 괴리 위험이 있었음."""
    from bithumb.binance_guard import load_config
    usdt = get_futures_usdt()
    if usdt is None:
        log.warning("[LIVE] 선물잔고 조회 실패(API) — 거래 보류, 다음 루프 재시도")
        return False
    if usdt <= 0:
        log.warning(f"[LIVE] 선물잔고 {usdt:.2f}(0 이하) — 거래 보류")
        return False
    cap = load_config().get("engine_caps_usdt", {}).get(ENGINE, 0)
    margin_base = min(usdt, cap)                    # 상한 안으로 제한
    target_notional = margin_base * target_frac * LEVERAGE
    res = guard.rebalance_long(target_notional)
    log.warning(f"[LIVE] 코어 목표명목 {target_notional:.1f} USDT"
                f"(증거금 min(잔고{usdt:.0f},상한{cap})×{target_frac:.0%}×{LEVERAGE:.0f}배) → {res}")
    # ★ 실제 주문이 나간 경우에만 알림(실전에서만 알림 원칙) — 스킵/dry는 로그만
    if res.get("live"):
        try:
            notify.send(f"[CORE-LEV] ★실전 리밸런싱 {target_frac:.0%}×{LEVERAGE:.0f}배 명목{target_notional:.0f}USDT @{price:,.0f}")
        except Exception: pass
    if res.get("dry") or res.get("error"):
        try: notify.send(f"🚨 [CORE-LEV] 리밸런싱 실패/차단 → {res} — state 유지, 다음 루프 재시도")
        except Exception: pass
        return False
    return True   # live(실주문 성공) 또는 skip(이미 목표 근접, 변화<5USDT라 사실상 동기화됨)


def main():
    s = load_state()
    ls = bn_live_status()
    _live = bool(ls.get("enabled")) and ENGINE in ls.get("armed", [])
    mode = f"🔴실전(바이낸스, {LEVERAGE:.0f}배)" if _live else "🔵순수모의(실주문 불가)"
    log.info(f"레버리지 코어 시작 [{mode}] — SMA{SMA_FAST}>SCOUT30%×{LEVERAGE:.0f}배 / "
             f"SMA{SMA_SLOW}>FULL100%×{LEVERAGE:.0f}배 | 상태={s['state']} 자산={s['equity']:,.0f}원 "
             f"| 가드 enabled={ls.get('enabled')} armed={ls.get('armed')}")
    try:
        notify.send(f"[CORE-LEV] 레버리지코어 시작 — {mode}")
    except Exception: pass

    while True:
        try:
            sig = sma_signal()
            if sig is None:
                time.sleep(CHECK_SEC); continue
            above50, above200 = sig
            try:
                price = binance_price()
            except Exception as e:
                log.warning(f"바이낸스 시세 조회 실패: {e}"); time.sleep(CHECK_SEC); continue

            target_frac = FULL_FRAC if above200 else (SCOUT_FRAC if above50 else 0.0)
            new_state = "FULL" if above200 else ("SCOUT" if above50 else "CASH")

            ls = bn_live_status()
            live = bool(ls.get("enabled")) and ENGINE in ls.get("armed", [])

            if live:   # ★ 실전 (가드 armed) — 바이낸스 실주문
                guard = BinanceGuard(ENGINE)
                if new_state != s["state"]:
                    if live_rebalance(guard, target_frac, price):
                        s["state"] = new_state; save_state(s)
                    # 실패 시 state 그대로 유지 — 다음 루프에서 new_state!=s["state"]가 다시
                    # 성립해 자동 재시도됨 (성공할 때까지 계속 시도, 조용히 포기하지 않음)
                else:
                    pos = get_position()
                    if pos is None:
                        # ★ 2026-08-20: 이전엔 pos['amt']를 바로 읽어 조회 실패 시
                        # TypeError로 죽었고(또는 구버전에서는 amt=0으로 조용히
                        # "무포지션"처럼 로깅됐음), 실포지션 감시가 그 사이 비었다.
                        log.warning("[LIVE] 포지션조회 실패 — 다음 루프 재확인 (state는 유지)")
                    else:
                        log.info(f"[LIVE] 유지 {s['state']} | BTCUSDT {price:,.2f} | 실포지션 {pos['amt']:.4f}BTC "
                                 f"(명목 {pos['notional']:.1f}USDT, 미실현 {pos['unrealized']:+.2f})")
                        # ★ 2026-09-02(사용자 승인 후 수정): 상태가 안 바뀌면 실포지션을 로그만
                        #   찍고 대조하지 않던 버그. 사용자가 수동으로 판 뒤 봇은 계속 "FULL"이라
                        #   믿으며 빈손으로 12일(2026-08-20~09-01)을 보냈고, 그 사이 BTC는 +12.7%
                        #   올랐다(강세 조건은 8/20에 켜졌다). 이제 목표와 실제를 매 사이클 대조해
                        #   허용오차를 넘으면 교정한다. 외부에서 늘어난 경우(캡 초과)도 같이 잡힌다.
                        _tgt = live_target_notional(target_frac)
                        if _tgt is None:
                            log.warning("[LIVE] 잔고조회 실패 — 실포지션 대조 건너뜀(다음 루프 재시도)")
                        else:
                            _gap = abs(pos["notional"] - _tgt)
                            # 허용오차는 (비율/절대값) 중 큰 값에 더해, **최소 주문 격자**보다도
                            # 커야 한다(위 MIN_QTY_STEP_BTC 주석 — 안 그러면 무한 재시도).
                            _tol = max(_tgt * DRIFT_TOL_FRAC, DRIFT_TOL_USDT,
                                       MIN_QTY_STEP_BTC * price * DRIFT_STEP_MULT)
                            if _gap > _tol:
                                log.warning(f"[LIVE] ★실포지션 괴리 감지 — 목표 {_tgt:.1f} vs 실제 "
                                            f"{pos['notional']:.1f} USDT (차 {_gap:.1f} > 허용 {_tol:.1f}) → 교정")
                                try:
                                    notify.send(f"🚨 [CORE-LEV] 실포지션 괴리 교정 — 목표 {_tgt:.0f} vs "
                                                f"실제 {pos['notional']:.0f} USDT (상태 {s['state']} 유지)")
                                except Exception: pass
                                live_rebalance(guard, target_frac, price)
                        # ★ 2026-08-20(기록감사 발견): docstring이 약속한 "청산위험 70%
                        # 경보"가 모의(mark_to_market) 경로에만 구현돼 있었고, 정작 실제
                        # 돈이 걸린 실전 경로엔 없었다. 이 포지션은 서버측 손절도 없어서
                        # 이게 유일한 조기경보다. margin_est는 진입 시 사이징 공식
                        # (증거금×LEVERAGE=명목)의 역산 근사치.
                        margin_est = pos["notional"] / LEVERAGE if LEVERAGE else 0
                        if margin_est > 0:
                            loss_frac = -pos["unrealized"] / margin_est
                            if loss_frac >= LIQ_WARN_FRAC:
                                msg = (f"🚨 [CORE-LEV] 청산위험 — 증거금 추정 대비 {loss_frac*100:.0f}% 손실 "
                                       f"(진입 {pos['entry']:,.0f} → 현재 {price:,.0f}, "
                                       f"미실현 {pos['unrealized']:+.1f}USDT) — 서버측 손절 없음, 수동 확인 필요")
                                log.error(msg)
                                try: notify.send(msg)
                                except Exception: pass
            else:      # 모의
                mark_to_market(s, price)
                apply_funding(s, price)
                if new_state != s["state"]:
                    rebalance(s, target_frac, price, f"{s['state']}→{new_state}")
                    s["state"] = new_state
                else:
                    log.info(f"유지 {s['state']} | BTCUSDT {price:,.2f} | 모의자산 {s['equity']:,.0f}원 "
                             f"({(s['equity']/NOTIONAL_KRW-1)*100:+.1f}%)")
                save_state(s)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    main()
