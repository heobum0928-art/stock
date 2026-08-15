"""
일봉 캔들 갱신기 (update_daily_candles) — data/candles_daily/*.json 일괄 최신화.

배경(2026-08-16): core_trader/core_leveraged/hybrid_trader/em_trader/retest_trader가 전부
이 디렉터리의 파일을 SMA50/200 신호 계산에 쓰는데, 정작 이 파일들을 갱신하는 스크립트가
하나도 없었음 — BTC_1d.json이 2026-08-05 이후 11일간 그대로 멈춰있던 것을 뒤늦게 발견.
그동안 이 봇들이 실제로는 11일 전 시점의 "추세"로 판단하고 있었던 것(코드 버그는 아니고
데이터 파이프라인 자체가 아예 없었던 인프라 공백).

동작: candles_daily/ 안의 모든 {COIN}_1d.json에 대해 빗썸 공개 API(get_daily_candles,
Upbit과 동일 포맷)로 최근 캔들을 가져와 기존 파일(오래된순 정렬)에 병합. 신규 파일은
안 만들고(기존에 있던 코인만 갱신), 날짜 중복은 건너뜀.

부가기능(2026-08-16, 사용자 요청): 갱신 직후 BTC가 SMA50에 근접(±NEAR_PCT% 이내)했으면
텔레그램으로 조기경보 — 지금은 추세전환 후에만 로그가 남는데, 전환 "임박"을 미리 알아야
core_trader류 실전전환 여부·담보재배분 같은 대비를 준비할 시간이 생김. 코인당 1일 1회만
알림(스팸 방지), core_trader.py와 동일 BAND(1%) 밴드 적용해 실제 신호기준과 일치시킴.

Run: python scripts/update_daily_candles.py (1회 실행, 스케줄러가 주기 호출)
"""
import sys, json, time, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
KST = timezone(timedelta(hours=9))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bithumb.client import BithumbClient

NEAR_PCT = 3.0   # SMA까지 이 % 이내로 근접하면 조기경보
ALERT_STATE_PATH = ROOT / "data" / "sma_proximity_alert_state.json"

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [CANDLE-UPD] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/update_daily_candles.log", encoding="utf-8")])
log = logging.getLogger(__name__)

CANDLE_DIR = ROOT / "data" / "candles_daily"
FETCH_COUNT = 15   # 최근 15일치 조회 — 스케줄 공백이 며칠 있었어도 따라잡도록 여유
SLEEP_SEC = 0.15    # 공개 API 연속호출 완충


def main():
    files = sorted(CANDLE_DIR.glob("*_1d.json"))
    client = BithumbClient()
    updated = 0
    failed = []
    for f in files:
        coin = f.stem.replace("_1d", "")
        try:
            existing = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"{coin}: 기존 파일 읽기 실패({e}), 스킵")
            failed.append(coin)
            continue
        seen = {c.get("candle_date_time_kst") for c in existing}
        try:
            fresh = client.get_daily_candles(f"KRW-{coin}", count=FETCH_COUNT)  # newest-first
            if not isinstance(fresh, list):
                raise ValueError(f"예상밖 응답형식: {type(fresh)} {str(fresh)[:100]}")
        except Exception as e:
            log.warning(f"{coin}: API 조회 실패({e})")
            failed.append(coin)
            time.sleep(SLEEP_SEC)
            continue
        new_rows = [c for c in fresh if c.get("candle_date_time_kst") not in seen]
        if new_rows:
            merged = existing + list(reversed(new_rows))  # oldest-first로 합침
            merged.sort(key=lambda c: c.get("candle_date_time_kst", ""))
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
            updated += 1
        time.sleep(SLEEP_SEC)

    latest_btc = None
    try:
        d = json.loads((CANDLE_DIR / "BTC_1d.json").read_text(encoding="utf-8"))
        latest_btc = d[-1].get("candle_date_time_kst") if d else None
    except Exception:
        pass
    log.info(f"갱신 완료 — 총 {len(files)}개 중 {updated}개 갱신, 실패 {len(failed)}개"
              f"{f' ({failed[:10]})' if failed else ''} | BTC 최신봉: {latest_btc}")

    check_sma_proximity()


def check_sma_proximity():
    """BTC가 SMA50/200에 근접(±NEAR_PCT% 이내)하면 텔레그램 조기경보. 1일 1회만."""
    try:
        d = json.loads((CANDLE_DIR / "BTC_1d.json").read_text(encoding="utf-8"))
        closes = [float(c["trade_price"]) for c in d]
        if len(closes) < 200:
            return
        cur = closes[-1]
        s50 = sum(closes[-50:]) / 50
        s200 = sum(closes[-200:]) / 200
    except Exception as e:
        log.warning(f"SMA 근접도 확인 실패: {e}")
        return

    today = datetime.now(KST).date().isoformat()
    state = {}
    try:
        state = json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    msgs = []
    for label, sma in (("SMA50(스카우트30%)", s50), ("SMA200(풀매수100%)", s200)):
        dist_pct = (cur / sma - 1) * 100
        below = cur < sma
        key = f"{label}:{today}"
        if abs(dist_pct) <= NEAR_PCT and key not in state:
            state[key] = True
            direction = "위로 돌파 임박(상승추세 전환 근접)" if below else "아래로 이탈 임박(하락추세 전환 근접)"
            msgs.append(f"⚠️ BTC {label} 근접 — {direction} (현재 {cur:,.0f}, {label.split('(')[0]} {sma:,.0f}, 거리 {dist_pct:+.1f}%)")

    if msgs:
        # 오래된 상태 정리(최근 3일만 유지, 파일 무한증가 방지)
        cutoff = (datetime.now(KST).date() - timedelta(days=3)).isoformat()
        state = {k: v for k, v in state.items() if k.rsplit(":", 1)[-1] >= cutoff}
        tmp = ALERT_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ALERT_STATE_PATH)
        try:
            from bithumb import notify
            notify.send("[추세조기경보]\n" + "\n".join(msgs), force=True)
        except Exception: pass
        for m in msgs:
            log.warning(m)


if __name__ == "__main__":
    main()
