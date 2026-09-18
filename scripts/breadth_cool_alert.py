"""시장 폭 식음 알림 — 주문 없음, 텔레그램 알림만.

2026-09-18 사용자 결정: 숏봇 신규진입을 끄고 "알트 동반 상승이 식으면 알려달라".
data/breadth_events.csv(breadth_monitor.py가 5분마다 기록)를 읽어,
breadth_6h의 최근 1시간(12행) 평균이 COOL 미만이면 한 번 알린다.
다시 HOT 이상으로 달아오르면 재무장한다.

문턱은 2026-09-18 실측 분포 기준으로 정했다(중앙 0.429, 0.70 = 94.6 퍼센타일).
이 알림은 '재개를 검토할 때'라는 신호일 뿐, 재개가 낫다는 근거는 아니다
(PREREG_BREADTH_GUARD.md 판정 보류).
"""
import sys, csv, time, json, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bithumb import notify

KST = timezone(timedelta(hours=9))
SRC = ROOT / "data" / "breadth_events.csv"
STATE = ROOT / "data" / "breadth_cool_alert_state.json"
COOL = 0.50      # 최근 1시간 평균 breadth_6h가 이 밑이면 "식음"
HOT = 0.70       # 이 이상이면 재무장
WINDOW = 12      # 5분 x 12 = 1시간
POLL_SEC = 300

logging.basicConfig(
    filename=ROOT / "logs" / "breadth_cool_alert.log",
    level=logging.INFO, format="%(asctime)s [BCOOL] %(message)s")
log = logging.getLogger()


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"armed": True}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")


def recent():
    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))[-WINDOW:]
    vals = [float(r["breadth_6h"]) for r in rows if r.get("breadth_6h")]
    return (sum(vals) / len(vals) if vals else None), (rows[-1]["time"] if rows else "")


def main():
    log.info(f"=== 시장 폭 식음 알림 시작 (COOL<{COOL}, HOT>={HOT}, 주문 없음) ===")
    s = load_state()
    while True:
        try:
            avg, last = recent()
            if avg is not None:
                if s.get("armed", True) and avg < COOL:
                    msg = (f"[시장폭] 알트 동반 상승이 식었습니다\n"
                           f"최근 1시간 평균 6시간 상승비율 {avg*100:.0f}% (기준 {COOL*100:.0f}% 미만)\n"
                           f"숏봇 재개를 검토할 시점입니다. 재개 여부는 직접 결정하세요.\n"
                           f"(기록 {last})")
                    if not notify.send(msg):   # 무음시간(00~06)엔 False → 다음 주기에 재시도
                        log.info(f"식음 감지 avg={avg:.3f} — 전송 보류(무음시간/실패), 재시도")
                        time.sleep(POLL_SEC)
                        continue
                    log.info(f"알림 전송 avg={avg:.3f}")
                    s["armed"] = False
                    s["last_alert"] = datetime.now(KST).isoformat()
                    save_state(s)
                elif not s.get("armed", True) and avg >= HOT:
                    s["armed"] = True
                    save_state(s)
                    log.info(f"재무장 avg={avg:.3f}")
                else:
                    log.info(f"avg={avg:.3f} armed={s.get('armed', True)}")
        except Exception as e:
            log.warning(f"오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
