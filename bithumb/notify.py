"""Telegram notification helper."""
import logging
import requests
import yaml
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_cfg = None


def _get_cfg() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    return _cfg


def _is_quiet_hours() -> bool:
    cfg = _get_cfg().get("telegram", {})
    qs = cfg.get("quiet_start", -1)
    qe = cfg.get("quiet_end", -1)
    if qs < 0 or qe < 0:
        return False
    h = datetime.now().hour
    if qs <= qe:
        return qs <= h < qe
    return h >= qs or h < qe  # 자정 걸치는 경우


# ── 알림 화이트리스트 (2026-07-03 사용자 요청: cascade 매수/매도/수익 외 전부 끔) ──
# 통과: 캐스케이드 진입/청산/실패경보 + 시스템 치명 경보(🚨). 나머지 봇 시작/진입/청산 알림 전부 차단.
# ★ 2026-08-25(버그헌터 발견, 즉시수정): "증거금 -N% 도달" 역행경보(⚠️)가 화이트리스트에
#   없어 **100% 차단**되고 있었다. 같은 날 도입한 기능인데(would_change_log 2026-08-25 (8)),
#   도입 시 화이트리스트 통과 여부를 검증하지 않았다. 실측: 오늘 PROMUSDT -20/-40/-60%
#   경보 3건이 로그에는 찍혔으나 텔레그램으로는 한 건도 가지 않았다.
#   이 경보는 "봇이 진입하고 사람이 보고 자른다"는 현재 운용방식의 **유일한 트리거**라
#   차단되면 그 방식 자체가 성립하지 않는다. 무음시간(00~06)에도 도달해야 하므로
#   아래 send()에서 🚨와 동일하게 force 처리한다.
ALLOW_PATTERNS = ["캐스케이드 진입", "캐스케이드 청산", "캐스케이드 매수 실패", "캐스케이드 매도 실패", "🚨", "[포지션현황]", "[추세조기경보]", "[크립토브리핑]", "증거금 -", "판 뒤"]


def _allowed(text: str) -> bool:
    return any(p in text for p in ALLOW_PATTERNS)


def send(text: str, force: bool = False) -> bool:
    """Send Telegram message. Skipped during quiet hours unless force=True.
    2026-07-03: 화이트리스트 미통과 메시지는 로그만 남기고 전송 생략."""
    cfg = _get_cfg().get("telegram", {})
    token = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")
    if not token or not chat_id:
        return False
    if not _allowed(text):
        log.debug(f"[Telegram] 화이트리스트 미통과 — 전송 생략: {text[:50]}")
        return False
    # ★ 2026-08-20(기록감사 발견) — 🚨(치명 경보) 메시지는 무음시간에도 항상 보낸다.
    # 이전엔 호출부가 force=True를 넘겨야만 무음시간을 뚫었는데, 실제로 그렇게
    # 부르는 곳이 프로젝트 전체에 1곳뿐이었다. "서버측 손절 검증 실패", "거래소엔
    # 포지션 열려있는데 청산 실패" 같은 경보 6곳이 00~06시엔 전부 조용히 사라지고
    # 있었음 — -442%/-106% 사고가 났던 바로 그 종류의 상황을 알릴 유일한 경로였다.
    if "🚨" in text or "증거금 -" in text:
        force = True
    if not force and _is_quiet_hours():
        log.debug("[Telegram] 무음 시간대 — 전송 생략")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.warning(f"[Telegram] 전송 실패: {e}")
        return False


def notify_detected(coin: str, first_price: float) -> None:
    send(f"<b>[신규 상장 감지]</b> {coin}/KRW\n첫 체결가: <b>{first_price:,.0f}원</b>")


def notify_buy(coin: str, entry_price: float, volume: float, cost_krw: float) -> None:
    send(  # 매수 체결은 무음 시간도 항상 전송
        f"<b>[매수 체결]</b> {coin}/KRW\n"
        f"단가: {entry_price:,.0f}원\n"
        f"수량: {volume:.6f}\n"
        f"투자금: {cost_krw:,.0f}원",
        force=True,
    )


def notify_sell(coin: str, pnl_krw: float, pnl_pct: float, reason: str) -> None:
    sign = "+" if pnl_krw >= 0 else ""
    send(  # 매도 체결은 무음 시간도 항상 전송
        f"<b>[매도 체결]</b> {coin}/KRW\n"
        f"사유: {reason}\n"
        f"손익: <b>{sign}{pnl_krw:,.0f}원 ({pnl_pct:+.2f}%)</b>",
        force=True,
    )


def notify_daily(total_pnl: float, count: int, win_rate: float) -> None:
    send(
        f"<b>[일일 리포트]</b>\n"
        f"거래: {count}건 | 승률: {win_rate*100:.1f}%\n"
        f"총 PnL: <b>{total_pnl:+,.0f}원</b>"
    )


def notify_error(msg: str) -> None:
    send(f"<b>[오류]</b> {msg}", force=True)  # 오류는 무음 무시


def notify_ci_daily(
    today_cnt: int, today_pnl: float, today_tp: int, today_sl: int, today_be: int,
    total_cnt: int, total_wr: float, total_pnl: float, go_target: int = 30,
) -> None:
    remaining = max(0, go_target - total_cnt)
    sign = "+" if today_pnl >= 0 else ""
    send(
        f"<b>📊 [CI 일일 리포트]</b>\n"
        f"오늘: {today_cnt}건 | TP{today_tp}/SL{today_sl}/BE{today_be} | <b>{sign}{today_pnl:,.0f}원</b>\n"
        f"\n<b>── 누적 ──</b>\n"
        f"총 {total_cnt}건 (GO까지 {remaining}건 남음)\n"
        f"승률 {total_wr:.0f}% | PnL <b>{total_pnl:+,.0f}원</b>",
        force=True,
    )
