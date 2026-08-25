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
# ★ 2026-08-19(울트라감사 발견): rsi_extreme_short_paper(엔진 rsishort)는 파일명에 paper가
# 붙어있지만 armed_engines에 등록된 실거래 봇이다 — 그런데 이 감사의 대상 파일 목록에
# 아예 없어서, 그 봇이 연 실전 마진숏은 무보호여도 아무도 몰랐다(THETAUSDT 실사례).
RSI_SHORT_POS = ROOT / "data" / "rsi_short_pos.json"
# ★ 2026-08-26(점검 발견): 완화판 봇(margin_short_wide_trader, 2026-08-25 신설)이 대상에서
# 빠져 있었다 — 08-19 rsi_short 누락과 **정확히 같은 재발**이다. 실거래 4건이 전부 이 파일에
# 있는데 이 감사는 "정상 — 모든 실전 포지션 서버측 보호 확인됨"을 출력하고 있었다.
# 새 봇을 만들 때 이 목록에 추가하는 것을 절차로 삼아야 한다.
WIDE_SHORT_POS = ROOT / "data" / "margin_short_wide_pos.json"


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

    # ★ 2026-08-19: venue != "futures"면 continue라 마진 경로가 통째로 감사에서 빠져있었음.
    # 마진숏은 애초에 서버측 스탑을 거는 코드 자체가 없으므로(margin_guard에 숏용
    # place_protective_stop 미구현) 조회조차 못 하지만, "무보호"라는 사실 자체는 알려야 한다.
    for label, path in (("마진숏", MSHORT_POS), ("RSI극단숏", RSI_SHORT_POS),
                        ("마진숏(완화)", WIDE_SHORT_POS)):
        if not path.exists():
            continue
        positions = json.loads(path.read_text(encoding="utf-8"))
        for sym, pos in positions.items():
            if not pos.get("live"):
                continue
            if pos.get("venue") == "futures":
                status = check_futures_order(sym, pos.get("stop_order_id"))
                if status == "check_failed":
                    print(f"({sym} 조회 실패 — 네트워크 문제 추정, 이번 회차는 판정 보류)")
                elif status != "ok":
                    problems.append(f"🚨 {label} {sym} 무보호({status}) — 서버측 손절 없음, 봇 감시에만 의존 중")
            else:
                status = check_margin_order(sym, pos.get("stop_order_id"))
                if status != "ok":
                    problems.append(f"🚨 {label} {sym}(마진) 무보호({status}) — 서버측 손절 없음, 봇 다운 시 손절 미실행")

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
