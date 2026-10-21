"""일회용 — 완화봇(margin_short_wide_trader)을 '열린 숏이 하나도 없을 때' 재시작해 새 상수(FUT_MARGIN_PER_TRADE)를 적용한다.
2026-10-21 사용자 결정(건당 손절 -20 → -10). 열린 포지션이 있을 때는 재시작하지 않는다(루틴 원칙).
재시작은 프로세스를 끄면 watchdog(30초 감시)이 다시 띄운다. 끝나면 스스로 종료한다.
Run: python scripts/restart_wide_when_flat.py
"""
import sys, json, time, subprocess, datetime as dt
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bithumb.binance_guard import _signed

POS = ROOT / "data" / "margin_short_wide_pos.json"
LOG = ROOT / "logs" / "restart_wide_when_flat.log"
TARGET = "margin_short_wide_trader.py"


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def open_shorts():
    r = _signed("GET", "/fapi/v2/positionRisk", {})
    if r.status_code != 200:
        return None
    return [p["symbol"] for p in r.json() if float(p.get("positionAmt", 0) or 0) < 0]


def pos_file_empty():
    try:
        d = json.loads(POS.read_text(encoding="utf-8"))
        return not d
    except Exception:
        return False


def pids():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match '" + TARGET + "' } | ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True).stdout.split()
    return [int(x) for x in out if x.isdigit()]


log("대기 시작 — 열린 숏이 없고 포지션 파일이 비면 완화봇 재시작")
while True:
    try:
        s = open_shorts()
        if s is None:
            log("포지션 조회 실패 — 재시도")
        elif s or not pos_file_empty():
            pass   # 열려 있음 — 계속 대기
        else:
            old = pids()
            log(f"열린 숏 없음 — 재시작 실행(기존 PID {old})")
            for p in old:
                subprocess.run(["taskkill", "/PID", str(p), "/F"], capture_output=True)
            for _ in range(24):          # 최대 2분 대기
                time.sleep(5)
                new = [x for x in pids() if x not in old]
                if new:
                    log(f"완화봇 재기동 확인 — 새 PID {new} (새 상수 적용)")
                    sys.exit(0)
            log("★ 재기동 확인 실패 — watchdog 상태 점검 필요")
            sys.exit(1)
    except Exception as e:
        log(f"오류: {e}")
    time.sleep(60)
