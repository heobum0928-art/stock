"""예약 상한 변경 — 사용자 결정(2026-10-28 "응"): FOMC 이후 trend3(이더·솔라나 롱) 엔진 상한을 올린다.
Run: python scripts/set_cap_at.py "2026-10-29 03:30" trend3 440
- 지정 시각까지 기다렸다가 binance_live_config.json 의 engine_caps_usdt[엔진]을 값으로 바꾼다(원자적 교체·검증).
- 안전 확인: 손실 중지선이 발동했거나(data/loss_stop_triggered.json) 선물 지갑이 1,100 아래면 올리지 않는다.
- 적용 후 trend3_live가 다음 점검(30분 이내)에 '원가 기준 추가 매수'로 부족분만 산다(가격 하락 시 물타기 없음).
- 되돌리려면 같은 설정을 이전 값(300)으로.
"""
import sys, os, json, time, datetime as dt
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CFG = ROOT / "data" / "binance_live_config.json"
LOG = ROOT / "logs" / "set_cap_at.log"
MIN_WALLET = 1100.0


def log(m):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


when = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M")
engine, value = sys.argv[2], float(sys.argv[3])
log(f"예약 시작 — {when:%Y-%m-%d %H:%M}에 {engine} 상한을 {value:g}으로 변경(조건 충족 시)")
while dt.datetime.now() < when:
    time.sleep(30)

from bithumb.binance_guard import _signed
wallet = None
try:
    r = _signed("GET", "/fapi/v2/account")
    if r.status_code == 200:
        wallet = float(r.json()["totalWalletBalance"])
except Exception as e:
    log(f"지갑 조회 예외: {e}")
if (ROOT / "data" / "loss_stop_triggered.json").exists():
    log("★ 중단: 손실 중지선이 발동된 상태라 상한을 올리지 않음"); sys.exit(0)
if wallet is None or wallet < MIN_WALLET:
    log(f"★ 중단: 지갑 {wallet} (기준 {MIN_WALLET:g} 미만 또는 조회 실패)라 상한을 올리지 않음"); sys.exit(0)

d = json.loads(CFG.read_text(encoding="utf-8"))
prev = d["engine_caps_usdt"].get(engine)
d["engine_caps_usdt"][engine] = value
tmp = str(CFG) + ".tmp"
Path(tmp).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
json.loads(Path(tmp).read_text(encoding="utf-8"))
os.replace(tmp, CFG)
now = json.loads(CFG.read_text(encoding="utf-8"))["engine_caps_usdt"][engine]
log(f"적용 완료 — {engine} 상한 {prev} → {now} (지갑 {wallet:.1f})")
