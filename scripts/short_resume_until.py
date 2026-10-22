"""한시적 숏 재개 — 사용자 지시(2026-10-22 "11시까지 풀어"): 지정 시각까지만 새 숏 진입을 허용하고, 시각이 되면 다시 막는다.
Run: python scripts/short_resume_until.py "2026-10-22 23:00"
- 재개: binance_live_config.json max_total_short_notional_usdt, margin_live_config.json engine_caps_usdt.mshort_wide 를 data/short_pause.json 의 이전 값으로.
- 시각이 되면: 두 값을 다시 1로(신규 진입 차단). 열린 포지션의 손절·청산은 영향 없음. 'mshort'(원본 마진)는 계속 1.
- 실패하거나 프로세스가 죽으면 '풀린 채'로 남을 수 있다 — 그래서 시작·종료 시 반드시 로그와 설정값을 확인한다.
"""
import sys, os, json, time, datetime as dt
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
BIN, MAR = ROOT / "data" / "binance_live_config.json", ROOT / "data" / "margin_live_config.json"
NOTE = ROOT / "data" / "short_pause.json"
LOG = ROOT / "logs" / "short_resume_until.log"


def log(m):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def edit(path, fn):
    d = json.loads(path.read_text(encoding="utf-8")); fn(d)
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(Path(tmp).read_text(encoding="utf-8"))
    os.replace(tmp, path)


def apply(resume):
    prev = json.loads(NOTE.read_text(encoding="utf-8"))["previous"]
    edit(BIN, lambda d: d.__setitem__("max_total_short_notional_usdt", prev["max_total_short_notional_usdt"] if resume else 1))
    edit(MAR, lambda d: d["engine_caps_usdt"].__setitem__("mshort_wide", prev["margin_caps"]["mshort_wide"] if resume else 1))
    b = json.loads(BIN.read_text(encoding="utf-8"))["max_total_short_notional_usdt"]
    m = json.loads(MAR.read_text(encoding="utf-8"))["engine_caps_usdt"]["mshort_wide"]
    log(f"{'재개' if resume else '다시 중지'} 적용 — 선물 숏 총한도 {b}, 마진 mshort_wide 캡 {m}")


deadline = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M")
log(f"시작 — {deadline:%Y-%m-%d %H:%M}까지 새 숏 진입 허용")
apply(True)
while dt.datetime.now() < deadline:
    time.sleep(20)
apply(False)
log("종료 — 신규 숏 진입 다시 차단됨")
