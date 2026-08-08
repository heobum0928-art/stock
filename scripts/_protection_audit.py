"""[감시] 실거래 포지션 보호상태 감사 (protection_audit) — 2026-08-07.

TSTUSDT 서버측 스탑 등록 실패(-4120, 바이낸스 Algo Order API 강제이전) 사고 이후 도입.
열려있는 모든 실전 포지션(마진숏 선물폴백 + 재량롱)에 대해 거래소 서버측 손절주문이
실제로 살아있는지 주기적으로 재검증 — 코드가 "등록했다"고 로그에 남겨도 실제 거래소에
없을 수 있으므로(오늘 사고처럼) 반드시 거래소 조회로 재확인.
무보호 포지션 발견 시 텔레그램 즉시 알림.
"""
import sys, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bithumb.binance_guard import _signed as fut_signed
from bithumb.margin_guard import _signed as margin_signed
from bithumb import notify

MSHORT_POS = ROOT / "data" / "margin_short_pos.json"
LONG_POS = ROOT / "data" / "margin_manual_long_pos.json"


def check_futures_order(sym: str, order_id) -> str:
    """반환: 'ok' | 'missing' | 'no_stop_id' | 'check_failed'. ★2026-08-07: Algo Order API.
    ★2026-08-08: 재부팅 직후 네트워크 미완전 기동 등 일시적 오류를 "무보호"로 오탐한 사고
    이후 — 확실히 200+NEW/TRIGGERED 등 명시적 응답 못 받으면 'missing' 대신 'check_failed'로
    구분(가짜경보 방지), 최대 3회 재시도."""
    if not order_id:
        return "no_stop_id"
    last_exc = None
    for _ in range(3):
        try:
            r = fut_signed("GET", "/fapi/v1/algoOrder", {"algoId": order_id})
            if r.status_code == 200:
                status = r.json().get("algoStatus")
                return "ok" if status == "NEW" else "missing"
            last_exc = f"HTTP {r.status_code}"
        except Exception as e:
            last_exc = str(e)
        time.sleep(2)
    print(f"  ({sym} 조회 3회 실패, 마지막 오류: {last_exc} — 네트워크 문제일 수 있음, 무보호로 단정 안 함)")
    return "check_failed"


def check_margin_order(sym: str, order_id) -> str:
    if not order_id:
        return "no_stop_id"
    try:
        r = margin_signed("GET", "/sapi/v1/margin/order", {"symbol": sym, "orderId": order_id, "isIsolated": "FALSE"})
        if r.status_code == 200 and r.json().get("status") in ("NEW", "PARTIALLY_FILLED"):
            return "ok"
        return "missing"
    except Exception:
        return "missing"


def main():
    problems = []

    if MSHORT_POS.exists():
        positions = json.loads(MSHORT_POS.read_text(encoding="utf-8"))
        for sym, pos in positions.items():
            if not pos.get("live") or pos.get("venue") != "futures":
                continue
            status = check_futures_order(sym, pos.get("stop_order_id"))
            if status == "check_failed":
                print(f"({sym} 조회 실패 — 네트워크 문제 추정, 이번 회차는 판정 보류)")
            elif status != "ok":
                problems.append(f"🚨 마진숏 {sym} 무보호({status}) — 서버측 손절 없음, 봇 감시에만 의존 중")

    if LONG_POS.exists():
        positions = json.loads(LONG_POS.read_text(encoding="utf-8"))
        for coin, pos in positions.items():
            if not pos.get("live"):
                continue
            sym = f"{coin}USDT"
            status = check_margin_order(sym, pos.get("stop_order_id"))
            if status != "ok":
                problems.append(f"🚨 재량롱 {sym} 무보호({status}) — 서버측 손절 없음, 봇 감시에만 의존 중")

    if problems:
        msg = "\n".join(problems)
        print(msg)
        try:
            notify.send(f"🚨 [보호상태 감사] 무보호 실거래 포지션 발견\n\n{msg}", force=True)
        except Exception as e:
            print(f"텔레그램 전송 실패: {e}")
    else:
        print("정상 — 모든 실전 포지션 서버측 보호 확인됨")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
