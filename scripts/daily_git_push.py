"""
일일 자동 git push (daily_git_push) — 2026-08-18.

로컬에서 이미 커밋된(리뷰 완료된) 변경사항을 GitHub 원격에 매일 자동으로 올린다.
★ 새로 커밋하거나 강제(force) push는 절대 안 함 — 순수하게 "이미 있는 커밋을 원격에
반영"만 한다. 커밋 자체는 지금까지와 동일하게 세션 안에서 사람이 요청할 때만 만들어짐.

원격이 로컬보다 앞서있는 경우(다른 곳에서 커밋이 생겼거나 충돌 가능성)는 안전하게
건너뛰고 텔레그램으로 알림만 보낸다 — 자동으로 merge/rebase 시도하지 않음(수동 확인 필요).

로그: logs/daily_git_push.log
Run: python scripts/daily_git_push.py (스케줄러가 매일 1회 호출)
"""
import sys, subprocess, logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [GITPUSH] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/daily_git_push.log", encoding="utf-8")])
log = logging.getLogger(__name__)


def run(cmd):
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60)


def main():
    fetch = run(["git", "fetch", "origin", "main"])
    if fetch.returncode != 0:
        log.error(f"fetch 실패: {fetch.stderr[:300]}")
        return

    ahead = run(["git", "rev-list", "--count", "origin/main..HEAD"])
    behind = run(["git", "rev-list", "--count", "HEAD..origin/main"])
    try:
        n_ahead = int(ahead.stdout.strip() or 0)
        n_behind = int(behind.stdout.strip() or 0)
    except ValueError:
        log.error(f"rev-list 파싱 실패: ahead={ahead.stdout!r} behind={behind.stdout!r}")
        return

    if n_ahead == 0:
        log.info("push할 커밋 없음(원격과 동일)")
        return

    if n_behind > 0:
        log.warning(f"원격이 로컬보다 {n_behind}건 앞서있음 — 충돌 위험, 자동push 건너뜀(수동 확인 필요)")
        try:
            from bithumb import notify
            notify.send(f"⚠️ 자동git push 건너뜀 — 원격이 로컬보다 {n_behind}건 앞서있음, 수동 확인 필요")
        except Exception:
            pass
        return

    push = run(["git", "push", "origin", "main"])
    if push.returncode == 0:
        log.info(f"push 완료 — {n_ahead}건 반영")
    else:
        log.error(f"push 실패: {push.stderr[:300]}")
        try:
            from bithumb import notify
            notify.send(f"⚠️ 자동git push 실패({n_ahead}건 대기 중): {push.stderr[:200]}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
