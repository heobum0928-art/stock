"""
일일 크립토 브리핑 전달기 (forward_daily_briefing) — 클라우드 에이전트가 커밋한
docs/daily_briefing_latest.md을 pull 받아서 텔레그램으로 전달.

배경(2026-08-16): 크립토 뉴스 오토리서치를 클라우드 예약 에이전트(trig_01GeikF6oLWL5G9gS78tLuMQ)로
매일 아침 8시(KST)에 돌리도록 설정. 클라우드 에이전트는 로컬 텔레그램 자격증명에 접근 못 하므로
결과를 저장소에 커밋만 하고, 이 스크립트가 pull 받아 로컬에서 텔레그램으로 전송하는 역할 분담.

동작: git pull → docs/daily_briefing_latest.md 읽기 → 마지막 전송 내용과 다르면(새 브리핑)
텔레그램 전송 → 전송 이력 저장(중복 전송 방지).

Run: python scripts/forward_daily_briefing.py (하루 1회, 스케줄러가 호출)
"""
import sys, subprocess, json, hashlib
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRIEFING_PATH = ROOT / "docs" / "daily_briefing_latest.md"
SENT_STATE_PATH = ROOT / "data" / "daily_briefing_sent_state.json"


def git_pull():
    try:
        r = subprocess.run(["git", "pull", "origin", "main"], cwd=str(ROOT),
                            capture_output=True, text=True, timeout=60)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)


def main():
    ok, out = git_pull()
    if not ok:
        print(f"[ERROR] git pull 실패: {out}")
        return

    if not BRIEFING_PATH.exists():
        print("브리핑 파일 없음 — 아직 클라우드 에이전트가 실행 전이거나 첫 실행 대기중")
        return

    text = BRIEFING_PATH.read_text(encoding="utf-8")
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    sent = {}
    try:
        sent = json.loads(SENT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    if sent.get("last_hash") == text_hash:
        print("이미 전송된 브리핑(변경 없음) — 스킵")
        return

    from bithumb import notify
    msg = "[크립토브리핑]\n" + text[:3500]  # 텔레그램 메시지 길이 여유
    ok_send = notify.send(msg, force=True)
    if ok_send:
        SENT_STATE_PATH.write_text(json.dumps({"last_hash": text_hash}, ensure_ascii=False), encoding="utf-8")
        print("전송 완료")
    else:
        print("[ERROR] 텔레그램 전송 실패 — 화이트리스트 확인 필요")


if __name__ == "__main__":
    main()
