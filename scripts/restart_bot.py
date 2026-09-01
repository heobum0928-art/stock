"""봇 하나를 안전하게 재시작한다(종료만 하면 watchdog이 새 코드로 다시 띄운다).

사용법:
    .venv\\Scripts\\python.exe scripts\\restart_bot.py core_leveraged
    .venv\\Scripts\\python.exe scripts\\restart_bot.py margin_short_trader

인자 없이 실행하면 재시작 가능한 봇 목록을 보여준다.
★ 실거래 봇을 재시작하면 그 봇의 규칙에 따라 실제 주문이 나갈 수 있다 —
  무엇이 재시작되는지 확인하고 실행할 것.
"""
import sys
import psutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN = ["core_leveraged", "margin_short_trader", "margin_short_wide_trader",
         "quietpump_long_paper", "prom_long_paper", "shadow_fleet", "tg_bot"]


def find(name: str):
    """해당 스크립트를 돌리는 파이썬 프로세스 전부(런처 부모 + 자식)."""
    target = f"{name}.py"
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if not (p.info["name"] and "python" in p.info["name"].lower()):
                continue
            if any(str(c).endswith(target) for c in (p.info["cmdline"] or [])):
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return out


def main():
    if len(sys.argv) < 2:
        print("사용법: python scripts/restart_bot.py <봇이름>")
        print("가능한 봇:")
        for k in KNOWN:
            print(f"  {k}  ({len(find(k))}개 실행 중)")
        return 1

    name = sys.argv[1].removesuffix(".py")
    procs = find(name)
    if not procs:
        print(f"'{name}' 실행 중인 프로세스가 없습니다. 이름을 확인하세요.")
        return 1

    print(f"'{name}' 프로세스 {len(procs)}개 종료 요청:")
    for p in procs:
        try:
            print(f"  PID {p.pid} 종료")
            p.terminate()
        except psutil.NoSuchProcess:
            print(f"  PID {p.pid} 이미 종료됨")
        except Exception as e:
            print(f"  PID {p.pid} 종료 실패: {e}")

    print("\n완료. watchdog이 30초 안에 새 코드로 다시 띄웁니다.")
    print(f"확인: logs/{name}.log 의 마지막 줄을 보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
