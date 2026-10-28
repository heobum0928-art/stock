"""
trend3 실거래 엔진 — ETH·SOL 200일선 추세 롱 (바이낸스 무기한선물, 1배).

만든 날 2026-10-13. ★ 기본 상태는 "꺼짐"이다: `armed_engines`에 "trend3"가 없거나
`engine_caps_usdt`에 "trend3"가 없으면 주문은 한 건도 안 나가고 신호만 기록한다(모의).
켜는 것(armed·캡·레버리지 설정)은 사용자가 직접 한다 — CLAUDE.md 6항.

규칙(PREREG_TREND200_PORT.md / scripts/trend3_paper.py와 동일):
  일봉 종가가 200일 평균선 ×1.01 위면 ON(보유), ×0.99 아래면 OFF(전량 매도), 그 사이는 직전 상태 유지.
  전일(마감된) 일봉으로만 판단한다. 규칙 자체에 가격 손절은 없다 — 퇴장은 200일선 이탈뿐이다.

비트코인은 의도적으로 뺐다: 이미 core_lev가 같은 계좌의 BTCUSDT를 들고 있고, 한 방향 모드에서는
같은 심볼 포지션이 합쳐져 서로의 "목표"를 어지럽힌다. BTC 몫은 core_lev가 맡는다.

안전장치(전부 기존 BinanceGuard 게이트 + 추가):
  - 레버리지는 이 파일의 LEVERAGE(=1)로 고정. 설정의 엔진별 레버리지가 다르면 주문 거부
    (설정에 leverage_by_engine.trend3=1을 넣지 않으면 전역 2배가 적용돼 게이트 계산이 틀어진다).
  - 다른 봇이 같은 심볼에 숏을 들고 있으면(amt<0) 건드리지 않고 다음 루프에서 재시도.
  - 매도는 "이 엔진이 산 수량"만, reduceOnly로. 사용자가 수동으로 판 경우 남은 만큼만.
  - 사이즈 = min(선물 가용잔고, 엔진캡) ÷ 2(종목 수) × LEVERAGE. 리밸런싱·드리프트 교정은 하지 않는다
    (거래가 연 몇 회뿐인 규칙 — 상태가 바뀔 때만 주문).

상태: data/trend3_live_state.json | 로그: logs/trend3_live.log
Run: python scripts/trend3_live.py [--once]
"""
import sys, os, atexit, time, json, socket, logging
from datetime import datetime
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ONCE = "--once" in sys.argv

_sock = None
def _single():
    global _sock
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try: _sock.bind(("127.0.0.1", 47262))
    except OSError: print("[ERROR] trend3_live 이미 실행 중 (포트 47262)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

import requests
from bithumb import notify
import bithumb.binance_guard as bg
from bithumb.binance_guard import BinanceGuard, live_status as bn_live_status, get_futures_usdt, \
    get_futures_position, engine_leverage, load_config

ENGINE = "trend3"
SYMS = ("ETHUSDT", "SOLUSDT")      # BTC는 core_lev 담당
LEVERAGE = 1
MA_DAYS = 200
BAND = 0.01
N_LEGS = len(SYMS)
CHECK_SEC = 1800
STATE_PATH = ROOT / "data" / "trend3_live_state.json"
FAPI = "https://fapi.binance.com"

Path(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [TREND3] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(ROOT / "logs" / "trend3_live.log", encoding="utf-8")])
log = logging.getLogger("trend3_live")


# ───────────────────────── 신호 (순수 함수 — 테스트 대상) ─────────────────────────
def hysteresis_state(closes, prev_on=None):
    """closes: 마감된 일봉 종가 리스트(오래된 → 최근). 200일선 ±1% 밴드 히스테리시스를 처음부터 재생.
    반환: (on, 마지막 종가, 마지막 200일 평균). 데이터가 200개 미만이면 (None, None, None)."""
    n = len(closes)
    if n < MA_DAYS:
        return None, None, None
    on = prev_on if prev_on is not None else 0
    csum = sum(closes[:MA_DAYS - 1])
    ma = None
    for i in range(MA_DAYS - 1, n):
        csum += closes[i]
        ma = csum / MA_DAYS
        px = closes[i]
        if px > ma * (1 + BAND):
            on = 1
        elif px < ma * (1 - BAND):
            on = 0
        csum -= closes[i - MA_DAYS + 1]
    return on, closes[-1], ma


def fetch_closes(sym, limit=1000):
    r = requests.get(f"{FAPI}/fapi/v1/klines", params=dict(symbol=sym, interval="1d", limit=limit), timeout=30)
    r.raise_for_status()
    return [float(k[4]) for k in r.json()[:-1]]       # 마지막(진행 중) 봉 제외


# ───────────────────────── 상태 ─────────────────────────
def load_state():
    if STATE_PATH.exists():
        try:
            s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            s.setdefault("on", {}); s.setdefault("qty", {})
            return s
        except Exception:
            pass
    return {"on": {}, "qty": {}}


def save_state(s):
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


# ───────────────────────── 주문 ─────────────────────────
class Trend3Guard(BinanceGuard):
    """BinanceGuard의 4중 관문(_gate)을 그대로 쓰되, BTCUSDT 고정이던 원장·레버리지를 심볼별로."""

    def ledger_sym(self, side, sym, qty, notional, result):
        import csv
        new = not bg.LEDGER.exists()
        try:
            with open(bg.LEDGER, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new: w.writerow(["time", "engine", "side", "symbol", "qty", "notional_usdt", "result"])
                w.writerow([datetime.now(bg.KST).strftime("%Y-%m-%d %H:%M:%S"), self.engine, side, sym,
                            f"{qty:.6f}", f"{notional:.2f}", str(result)[:200]])
        except Exception as e:
            log.warning(f"원장 기록 실패: {e}")

    def buy(self, sym, target_notional, gate_notional=None):
        """sym 롱을 target_notional(USDT)만큼 시장가 매수. 게이트는 gate_notional(기본: target_notional) 기준.
        추가 매수(top-up)는 부족분만 사되 게이트는 총 목표로 본다. 반환 dict: live / dry / skip / error."""
        ok, reason = self._gate(gate_notional if gate_notional is not None else target_notional)
        if not ok:
            self.ledger_sym("buy", sym, 0, target_notional, f"DRY:{reason}")
            return {"dry": True, "reason": reason}
        price = bg._mark_price(sym)
        if price <= 0:
            return {"error": "가격 조회 실패"}
        step, min_notional = bg._symbol_filters_futures(sym)
        if step <= 0:
            return {"error": "LOT_SIZE 조회 실패"}
        qty = bg._round_step(target_notional / price, step)
        if qty <= 0 or qty * price < min_notional:
            return {"skip": True, "reason": f"최소주문 미달(수량{qty}, 명목{qty*price:.1f}<{min_notional})"}
        try:
            bg._signed("POST", "/fapi/v1/leverage", {"symbol": sym, "leverage": LEVERAGE})
            r = bg._signed("POST", "/fapi/v1/order", {"symbol": sym, "side": "BUY", "type": "MARKET",
                                                      "quantity": qty, "newOrderRespType": "RESULT"})
            res = r.json()
            if r.status_code != 200:
                self.ledger_sym("BUY", sym, qty, target_notional, f"ERR:{res}")
                return {"error": res}
        except Exception as e:
            self.ledger_sym("BUY", sym, qty, target_notional, f"ERR:{e}")
            return {"error": str(e)}
        executed = float(res.get("executedQty", 0) or 0) or qty
        self.ledger_sym("BUY", sym, executed, executed * price, res)
        return {"live": True, "qty": executed, "result": res}

    def sell(self, sym, qty):
        """sym 롱 qty만큼 reduceOnly 시장가 매도 + 실현손익 기록."""
        step, _ = bg._symbol_filters_futures(sym)
        if step <= 0:
            return {"error": "LOT_SIZE 조회 실패"}
        qty = bg._round_step(qty, step)
        if qty <= 0:
            return {"skip": True, "reason": "수량 0"}
        try:
            r = bg._signed("POST", "/fapi/v1/order", {"symbol": sym, "side": "SELL", "type": "MARKET",
                                                      "quantity": qty, "reduceOnly": "true",
                                                      "newOrderRespType": "RESULT"})
            res = r.json()
            if r.status_code != 200:
                self.ledger_sym("SELL", sym, qty, 0, f"ERR:{res}")
                return {"error": res}
        except Exception as e:
            self.ledger_sym("SELL", sym, qty, 0, f"ERR:{e}")
            return {"error": str(e)}
        executed = float(res.get("executedQty", 0) or 0) or qty
        self.ledger_sym("SELL", sym, executed, 0, res)
        try:
            oid = res.get("orderId")
            tr = bg._signed("GET", "/fapi/v1/userTrades", {"symbol": sym, "limit": 50})
            if tr.status_code == 200:
                realized = sum(float(t.get("realizedPnl", 0) or 0) for t in tr.json() if t.get("orderId") == oid)
                if realized:
                    self.record_realized(realized)
                    log.info(f"[{sym}] 실현손익 {realized:+.2f} USDT 기록")
        except Exception as e:
            log.warning(f"[{sym}] 실현손익 기록 예외: {e}")
        return {"live": True, "qty": executed, "result": res}


_ALERT_LAST = {}
def _alert_once(key, text, gap_sec):
    now = time.time()
    if now - _ALERT_LAST.get(key, 0) < gap_sec:
        return
    _ALERT_LAST[key] = now
    try: notify.send(text)
    except Exception: pass


def is_live():
    ls = bn_live_status()
    cfg = load_config()
    return (bool(ls.get("enabled")) and ENGINE in ls.get("armed", [])
            and cfg.get("engine_caps_usdt", {}).get(ENGINE) is not None)


def _wallet_usdt():
    """선물 지갑잔고(totalWalletBalance, 미실현 제외). 가용잔고는 숏 봇 증거금에 따라 흔들려 쓰지 않는다. 실패 시 None."""
    try:
        r = bg._signed("GET", "/fapi/v2/account")
        if r.status_code == 200:
            return float(r.json().get("totalWalletBalance"))
        log.warning(f"지갑잔고 조회 실패 status={r.status_code}")
    except Exception as e:
        log.warning(f"지갑잔고 조회 실패: {e}")
    return None


def leg_margin(cfg):
    usdt = _wallet_usdt()
    if usdt is None or usdt <= 0:
        return None
    cap = cfg.get("engine_caps_usdt", {}).get(ENGINE, 0)
    return min(usdt, cap) / N_LEGS


def maybe_top_up(guard, s, sym, pos, px):
    """★ 2026-10-28: 이미 ON이고 보유 중인 종목의 **매입 원가**가 목표(지갑·캡 기준)보다 부족하면 부족분만 추가 매수.
    평가액이 아니라 원가(entryPrice×수량) 기준이라 가격이 떨어져도 물타기가 되지 않는다. 줄이는 일은 없다(매도는 200일선 이탈 때만)."""
    tracked = float(s["qty"].get(sym, 0.0) or 0.0)
    if tracked <= 0 or pos["amt"] <= 0 or pos["entry"] <= 0:
        return
    cfg = load_config()
    if engine_leverage(ENGINE, cfg) != LEVERAGE:
        return
    margin = leg_margin(cfg)
    if margin is None:
        return
    target = margin * LEVERAGE
    invested = pos["entry"] * pos["amt"]
    gap = target - invested
    step, min_notional = bg._symbol_filters_futures(sym)
    tol = max(target * 0.15, 10.0, min_notional * 1.5)
    if gap <= tol:
        return
    res = guard.buy(sym, gap, gate_notional=target)
    log.warning(f"[{sym}] 추가 매수: 원가 {invested:.1f} → 목표 {target:.1f}(부족 {gap:.1f}) → {res.get('live') and 'LIVE' or res}")
    if res.get("live"):
        s["qty"][sym] = tracked + float(res["qty"]); save_state(s)


def step_symbol(guard, s, sym, on, px, ma, live):
    """한 종목의 한 사이클. 상태가 바뀌었거나 아직 포지션이 없을 때만 주문."""
    tracked = float(s["qty"].get(sym, 0.0) or 0.0)

    if not live:
        # 모의: 신호만 기록(실주문 불가). 추적 수량은 건드리지 않는다.
        log.info(f"[{sym}] {'ON' if on else 'OFF'} (모의, 종가 {px:,.2f} / 200일선 {ma:,.2f})")
        return

    pos = get_futures_position(sym)
    if pos is None:
        log.warning(f"[{sym}] 포지션 조회 실패 — 다음 루프 재시도")
        return

    if on and tracked <= 0:
        if pos["amt"] < 0:
            log.warning(f"[{sym}] 다른 봇의 숏이 열려 있음(amt={pos['amt']}) — 매수 보류, 다음 루프 재시도")
            return
        if pos["amt"] > 0:
            # 이미 롱이 있다(사용자 수동 또는 이전 실행의 추적 누락) — 이중 매수 금지, 그 수량을 인수.
            log.warning(f"[{sym}] 기존 롱 {pos['amt']} 발견 — 매수하지 않고 추적 수량으로 인수")
            s["qty"][sym] = pos["amt"]; save_state(s)
            return
        cfg = load_config()
        if engine_leverage(ENGINE, cfg) != LEVERAGE:
            _alert_once("lev_mismatch",
                        f"🚨 [TREND3] 설정 레버리지({engine_leverage(ENGINE, cfg)}배)가 엔진 고정값({LEVERAGE}배)과 달라 "
                        f"주문 거부 — binance_live_config.json의 leverage_by_engine에 trend3: {LEVERAGE} 추가 필요", 6 * 3600)
            log.error("레버리지 설정 불일치 — 주문 거부")
            return
        margin = leg_margin(cfg)
        if margin is None:
            log.warning("[LIVE] 선물잔고 조회 실패 — 매수 보류")
            return
        target = margin * LEVERAGE
        res = guard.buy(sym, target)
        log.warning(f"[{sym}] ON 전환 → 매수 목표 명목 {target:.1f} USDT(증거금 {margin:.1f}×{LEVERAGE}배) → {res}")
        if res.get("live"):
            s["qty"][sym] = float(res["qty"]); save_state(s)
            try: notify.send(f"[TREND3] ★{sym} 롱 진입 {res['qty']} @~{px:,.2f}")
            except Exception: pass
        elif res.get("error"):
            _alert_once(f"buy_err_{sym}", f"🚨 [TREND3] {sym} 매수 오류 → {res.get('error')}", 6 * 3600)

    elif (not on) and tracked > 0:
        sell_qty = min(tracked, max(pos["amt"], 0.0))
        if sell_qty <= 0:
            log.warning(f"[{sym}] OFF 전환인데 실제 롱이 없음(추적 {tracked}) — 추적만 비움(수동 청산 추정)")
            s["qty"][sym] = 0.0; save_state(s)
            return
        res = guard.sell(sym, sell_qty)
        log.warning(f"[{sym}] OFF 전환 → 매도 {sell_qty} → {res}")
        if res.get("live"):
            s["qty"][sym] = max(0.0, tracked - float(res["qty"])); save_state(s)
            try: notify.send(f"[TREND3] ★{sym} 롱 청산 {res['qty']} @~{px:,.2f} (200일선 이탈)")
            except Exception: pass
        elif res.get("error"):
            _alert_once(f"sell_err_{sym}", f"🚨 [TREND3] {sym} 매도 오류 → {res.get('error')}", 3600)
    else:
        log.info(f"[{sym}] 유지 {'ON' if on else 'OFF'} | 종가 {px:,.2f} / 200일선 {ma:,.2f} | "
                 f"추적 {tracked} / 실제 {pos['amt']}")
        if on:
            maybe_top_up(guard, s, sym, pos, px)


def main():
    s = load_state()
    live = is_live()
    log.info(f"trend3 시작 [{'🔴실전' if live else '🔵모의(신호만 기록)'}] 종목={SYMS} 레버리지={LEVERAGE}배 "
             f"| 상태={s['on']} 추적수량={s['qty']}")
    guard = Trend3Guard(ENGINE)
    while True:
        try:
            live = is_live()
            for sym in SYMS:
                try:
                    closes = fetch_closes(sym)
                except Exception as e:
                    log.warning(f"[{sym}] 일봉 조회 실패: {e}")
                    continue
                prev = s["on"].get(sym)
                # 상태 파일이 없을 때만 전체 재생(히스테리시스의 올바른 현재 상태). 이후엔 최근 봉 하나로 갱신.
                if prev is None:
                    on, px, ma = hysteresis_state(closes)
                else:
                    on, px, ma = hysteresis_state(closes[-(MA_DAYS + 1):], prev_on=prev)
                if on is None:
                    log.warning(f"[{sym}] 일봉 {len(closes)}개 < {MA_DAYS} — 판단 보류")
                    continue
                if prev is not None and on != prev:
                    log.warning(f"[{sym}] ★신호 전환 {'ON' if prev else 'OFF'} → {'ON' if on else 'OFF'} "
                                f"(종가 {px:,.2f} / 200일선 {ma:,.2f})")
                s["on"][sym] = on
                save_state(s)
                step_symbol(guard, s, sym, on, px, ma, live)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"루프오류: {e}")
        if ONCE:
            break
        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    main()
