"""
손실 중지선 감시 — 사용자 지시(2026-10-21): "앞으로 100달러 더 손해면 거래중지".

기준: data/loss_stop_baseline.json (기록 시각 이후 선물 계좌의 순손익 = 실현손익 + 수수료 + 펀딩).
      입출금(이체)은 세지 않는다 — 거래소 income 내역의 REALIZED_PNL / COMMISSION / FUNDING_FEE만 합산.
발동: 합계가 -LIMIT(100) 이하가 되면
  ① binance_live_config.json 의 max_total_short_notional_usdt 를 1로 낮춘다(원래 값은 기록).
     → open_short_futures()가 매 호출마다 이 값을 읽어 새 숏 진입을 모두 "dry"로 막는다.
  ② 이미 열린 포지션의 손절·만기 청산, 롱(core_lev·trend3)은 건드리지 않는다.
     ※ armed_engines에서 엔진을 빼는 방식은 쓰지 않는다 — close_short_futures()가 미arm이면 청산을 막는다.
  ③ data/loss_stop_triggered.json 에 시각·누적손익·원래 값·재개 방법을 남긴다.
발동 뒤에는 스스로 풀지 않는다. 재개는 사용자가 직접(triggered 파일 삭제 + 설정 값 복원).

한계: 마진 계좌(mshort, mshort_wide 마진 경로)는 이 감시 범위 밖이다. 선물 계좌 기준이다.
Run: python scripts/loss_stop_watch.py [--dry] [--once]
  --dry  발동 조건이어도 설정을 쓰지 않고 "발동했을 것"만 출력   --once 한 번만 확인하고 종료
"""
import sys, os, json, time, atexit, socket, logging, datetime as dt
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DRY = "--dry" in sys.argv
ONCE = "--once" in sys.argv

_sock = None
def _single():
    global _sock
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try: _sock.bind(("127.0.0.1", 47263))
    except OSError: print("[ERROR] loss_stop_watch 이미 실행 중 (포트 47263)."); sys.exit(1)
    atexit.register(_sock.close)
if not (DRY or ONCE):
    _single()

from bithumb.binance_guard import _signed, CONFIG
from bithumb import notify

KST = dt.timezone(dt.timedelta(hours=9))
LIMIT = 100.0
CHECK_SEC = 60
BASE = ROOT / "data" / "loss_stop_baseline.json"
TRIG = ROOT / "data" / "loss_stop_triggered.json"
KEY = "max_total_short_notional_usdt"
BLOCK_VALUE = 1

(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [LOSSSTOP] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(ROOT / "logs" / "loss_stop_watch.log", encoding="utf-8")])
log = logging.getLogger("loss_stop_watch")


def baseline_ms():
    b = json.loads(BASE.read_text(encoding="utf-8"))
    t = dt.datetime.fromisoformat(b["recorded_at_kst"])
    return int(t.timestamp() * 1000), b


def cum_pnl(since_ms):
    """since_ms 이후 실현손익+수수료+펀딩 합계. 조회 실패 시 None."""
    total, t = 0.0, since_ms
    while True:
        r = _signed("GET", "/fapi/v1/income", {"startTime": t, "limit": 1000})
        if r.status_code != 200:
            log.warning(f"income 조회 실패 {r.status_code} {r.text[:120]}")
            return None
        rows = r.json()
        if not isinstance(rows, list):
            return None
        for x in rows:
            if x.get("incomeType") in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
                total += float(x["income"])
        if len(rows) < 1000:
            return total
        t = int(rows[-1]["time"]) + 1


def trigger(cum):
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    prev = cfg.get(KEY)
    info = {"triggered_at_kst": dt.datetime.now(KST).isoformat(timespec="seconds"),
            "cum_pnl_since_baseline_usdt": round(cum, 2), "limit_usdt": LIMIT,
            "previous_" + KEY: prev, "set_" + KEY: BLOCK_VALUE,
            "resume": f"data/loss_stop_triggered.json 삭제 + binance_live_config.json 의 {KEY} 를 {prev} 로 복원"}
    if DRY:
        log.warning(f"[DRY] 발동 조건 충족(누적 {cum:+.2f}) — 설정은 쓰지 않음. 쓰려던 값: {KEY} {prev} → {BLOCK_VALUE}")
        return
    cfg[KEY] = BLOCK_VALUE
    tmp = str(CONFIG) + ".tmp"
    Path(tmp).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(Path(tmp).read_text(encoding="utf-8"))            # 쓰기 검증: 깨진 JSON이면 여기서 예외 → 교체 안 함
    os.replace(tmp, CONFIG)
    TRIG.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    log.error(f"★★ 손실 중지선 발동 — 누적 {cum:+.2f} USDT ≤ -{LIMIT:.0f}. 새 숏 진입 차단({KEY} {prev}→{BLOCK_VALUE}). 롱·기존 포지션 청산은 유지.")
    try:
        notify.send(f"[손실중지] 기준선 이후 누적 {cum:+.1f} USDT — 새 숏 진입을 막았습니다(청산·롱은 유지).")
    except Exception:
        pass


def main():
    since, b = baseline_ms()
    log.info(f"시작 dry={DRY} | 기준 {b['recorded_at_kst']} 지갑 {b['wallet_usdt']} | 중지선 -{LIMIT:.0f} USDT(순손익 기준)")
    fails = 0
    while True:
        try:
            if TRIG.exists():
                log.info("이미 발동됨(data/loss_stop_triggered.json) — 감시만 유지, 추가 조치 없음")
            else:
                cum = cum_pnl(since)
                if cum is None:
                    fails += 1
                    if fails in (5, 30):
                        log.error(f"income 조회 {fails}회 연속 실패 — 중지선 확인 불가")
                else:
                    fails = 0
                    log.info(f"기준선 이후 순손익 {cum:+.2f} USDT (중지선 -{LIMIT:.0f})")
                    if cum <= -LIMIT:
                        trigger(cum)
        except Exception as e:
            log.error(f"루프오류: {e}")
        if ONCE:
            break
        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    main()
