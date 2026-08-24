"""
마진 숏 실전 트레이더 (margin_short_trader) — 급등주 되돌림 숏 (바이낸스 크로스마진).

★ 규칙(2026-07-12 확정, 2026-07-22 재검증 후 파라미터만 갱신): LOOKBACK_H시간 +PUMP_PCT% 급등
   → HOLD_H시간 숏(+STOP_PCT% 스탑), 2배. 현재값: 7h+30%→48h(+40%). 최초 채택은 6h+40%였고
   2026-07-22에 세밀 재검증(4~8h×30~50% 격자)으로 7h+30%로 교체(신호빈도 약2배, TEST t+3.28) —
   상세 근거는 파일 상단 상수 정의부(LOOKBACK_H 근처) 주석 참조.
   (원 스위프: 2h~72h × 문턱20~60%, 날짜클러스터 t — 24h+40%는 TE+18%/t1.69로 열등,
   짧은 시간대일수록 되돌림이 확실하다는 게 핵심 발견.)

동작:
  ① 24h 변동률로 1차 스크리닝 → 후보만 5분봉으로 LOOKBACK_H시간 상승률 정밀계산
     (함수/변수명 pump_6h·ret6h는 최초 6h 버전의 잔재 — 지금은 LOOKBACK_H를 그대로 씀, 이름과
     실제 시간이 다를 수 있으니 착각 주의)
  ② margin_guard로 크로스마진 숏 진입(증거금 상한 내, 4중 관문)
  ③ STOP_PCT% 스탑 또는 HOLD_H시간 만기 시 자동 청산(되사서 상환)
  ④ 손익 기록.

★ margin_guard OFF면 자동 dry. 실전은 data/margin_live_config.json arm 필요(현재 arm됨).
포지션 data/margin_short_pos.json | 기록 data/margin_short_trades.csv | 로그 logs/margin_short_trader.log
포트 47251. Run: python scripts/margin_short_trader.py
"""
import sys, os, atexit, time, json, csv, socket, logging, statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
KST = timezone(timedelta(hours=9))

_sock = None
def _single():
    global _sock
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try: _sock.bind(("127.0.0.1", 47251))
    except OSError: print("[ERROR] margin_short_trader 이미 실행 중 (포트 47251)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests
from bithumb import notify
from bithumb.margin_guard import MarginGuard, live_status, get_margin_usdt, load_config, get_borrowed
from bithumb.binance_guard import BinanceGuard, load_config as load_futures_config, get_futures_usdt

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [MSHORT] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/margin_short_trader.log", encoding="utf-8")])
log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"; BASE = "https://api.binance.com"
ENGINE = "mshort"
POLL_SEC = 60  # ★ 2026-08-10: 300→60. 3개AI(ChatGPT·제미나이·Manus) 공통권고 —
# 트레일링 반납폭이 정확히 안 잡히는 원인이 폴링 갭(TST#2: MFE+25%→5분새 -7%까지 못 잡음)
# 이었다는 데 만장일치. 트레일링 숫자(15%p/10%p) 자체는 과최적화 우려로 보류, 폴링만 개선.

# ★★ 2026-07-12 시간대 전수 스위프 (2h~72h × 문턱20~60%, 40조합, 날짜클러스터 t) — 24h는 나쁜 선택이었음.
#   짧은 시간대일수록 압도적으로 좋음. 길수록 급격히 악화(24h t1.69 → 48h t0.10 → 72h t0.06).
#   "짧은 시간에 급하게 오른 것"이 확실히 되돌아옴. 24h+에 걸쳐 서서히 오른 건 진짜 추세일 수 있어 숏이 위험.
#     24h+40%(이전): 8.2건/주, TE +18.0%(t1.69), 승73%, 청산1%
#     6h+40%(2026-07-12~07-22 실전 사용): 4.5건/주, TE +38.8%(t4.60), 승86%, 청산0%
# 이전 반성: 2h vs 24h 둘만 비교하고 중간(4~6h)을 안 봐서 24h를 골랐던 것. 사용자가 "24h에 걸 필요 없다" 지적.
#
# ★★ 2026-07-22 재검증 — 5x5 세밀 격자(4~8h × 30~50%, 111코인·90일 5분봉, TRAIN60/TEST40).
#   6h+40%가 견고한 구간(주변 전부 t>1.4로 무너지는 곳 없음) 안에 있음은 재확인. 단 "더 잦은 신호"를
#   원하는 사용자 요청으로 30% 열(더 헐렁한 문턱)만 놓고 TRAIN t 기준 재선정(사후 TEST편향 없이) →
#   7h가 최고(TRAIN t+2.79). TEST로 확인: TRAIN n57 t+2.79 → TEST n39 t+3.28(TRAIN보다 오히려 강함,
#   과최적화 징후 없음). 표본합계 49→96건(약2배), 채택.
#   ★ 실전 미검증 주의: 위 백테스트는 최근 90일 재구성치라 2026-07-12 원 스위프(더 긴 기간)와 다른
#   창(window)임 — "6h+40%가 나쁘다"가 아니라 "7h+30%가 최근 창에서 더 낫고 표본도 더 많다"는 것.
PUMP_PCT = 30.0            # 상승률 문턱 (2026-07-22: 40→30, 신호빈도 증대 목적, TEST t+3.28 확인)
PUMP_PCT_MAX = 40.0        # ★ 2026-08-08: 상단 컷 신설. 백테스트 101건 급등폭 구간분석 결과
                            # 30~35%(n=82,승66%,+2.79%)·35~40%(n=15,승73%,+7.04%) 양호했으나
                            # 40%+(n=4)는 전패(-6~-40%) — ChatGPT/Perplexity 교차검증 후 "문턱을
                            # 높이지 말고 대신 과도한 급등(40%+)만 상단컷"으로 결론. n=4라 약한
                            # 신호지만 세력개입/뉴스성 급등은 평균회귀 논리가 깨질 수 있다는 가설.
LOOKBACK_H = 7             # ★ 7시간 상승률 기준 (2026-07-22: 6→7, TRAIN t 기준 재선정)
LOOKBACK = 84              # 7h = 5분봉 84개 (LOOKBACK_H*12)
VOL_MULT = 0.0            # 거래량 필터 미사용 (검증 결과 불필요)
HOLD_H = 48
STOP_PCT = 40.0           # 진입가 대비 +40% 상승 시 손절(2배 청산선 +50% 안쪽)

# ★ 2026-08-24: 마진 숏 서버측 손절(거래소에 STOP_LOSS 주문 사전등록) — 기본 OFF.
#   배경: 2026-08-07 서버측 스탑 도입 때 선물 숏·마진 롱만 커버되고 마진 숏이 빠져 있었다.
#   봇 5분 폴링(종가)만으론 봉내 급등을 못 잡아 손절선을 뚫는다(그림자 실측 최대 +13.7%p 초과).
#   손절선(STOP_PCT)은 바꾸지 않는다 — 작동 방식만 정확해진다.
#
#   ⚠️ 51건 관문 진행 중이나 **2026-08-24 사용자 결정으로 즉시 적용**한다.
#      DEADLINES.md 부칙3(확증 표본 중 규칙 변경 금지)과의 관계:
#        - 손절선·진입조건·보유기간 등 **판정 대상 파라미터는 하나도 바꾸지 않는다**
#        - 바뀌는 것은 "이미 있는 -40% 손절이 봉내에도 실제로 걸리는가" 뿐이다
#        - 마진 경로는 실거래 50건 중 1건(TUT)뿐이라 판정 영향이 사실상 없다
#        - 선물 경로(49건)는 2026-08-07부터 이미 같은 보호를 쓰고 있었다 — 오히려 일관성 복구
#      그럼에도 실행 방식 변경이므로 51건 판정문에 이 사실을 명시할 것.
#   문제 발생 시 이 값을 False 로 되돌리고 봇 재시작하면 즉시 이전 동작으로 복귀한다.
SERVER_STOP_MARGIN = True
TRAIL_TRIGGER_PCT = 15.0  # ★ 2026-08-10: 최유리(가격하락) 15%p 이상 찍으면 트레일링 무장
TRAIL_GIVEBACK_PCT = 10.0  # 그 최고점에서 10%p 반납하면 즉시 청산(48h/스탑 기다리지 않음)
COOLDOWN_H = 12           # 코인당 재진입 쿨다운
STRIKE_BLACKLIST_H = 24*7  # ★ 2026-08-09: 같은 코인이 연속 2회 스탑(-40%)에 걸리면 7일 블랙리스트
                            # (TUTUSDT 2연패 계기 — 신호가 특정 코인과 구조적으로 안 맞을 가능성 대응,
                            # 48h만기 청산은 정상 승리로 취급해 연속카운트 리셋)
# ★ 2026-08-15(버그헌터 발견): 기존 100은 스탑(-40%) 1회만 걸려도 100×2×0.40=80USDT로
#   daily_loss_limit(45)을 넘어감 — 지금까지 34건 전부 대출재고부족으로 선물폴백 경로만
#   타서(마진경로 실거래 0건) 잠복해 있던 문제. 대출재고가 확보돼 이 경로가 열릴 경우를
#   대비해 45/(2×0.40)=56.25 이하로 낮춤(50, 선물폴백 사이징과 비슷한 규모로 통일).
MARGIN_PER_TRADE = 50.0  # 증거금(상한과 동일). 실제 사용은 min(잔고,상한)
# ★ 2026-07-27: 실전표본 확보속도 문제(하루 신호 2~3건인데 대부분 누적노출초과로 차단) —
#   Gemini/ChatGPT/Manus 3개 AI 교차검증 후 채택: 선물폴백 경로만 건당 사이즈를 줄여
#   fcap(60) 안에서 동시 3건 허용(20×3=60). 마진 경로(MARGIN_PER_TRADE)는 그대로 둠 —
#   지금까지 실거래(ERA·DEXE·EUL)가 전부 대출재고부족으로 선물폴백 경로를 탔기 때문에
#   병목이 여기 있음. 3건 동시손절 최대손실 3×20×2배×40%=48USDT, 기존 단일포지션(40)과
#   거의 동일 — 세 AI 공통 권고대로 10건이 아닌 3건부터 시작, 상관관계·슬리피지 실측 후 확대검토.
# ★ 2026-08-02: MMT 건이 크게 터진 것(+55%대)을 보고 사용자가 사이즈 확대 요청.
#   07-27 축소 취지(표본 확보)는 유지하되 소폭만: 20→25(25%↑). 4건 동시 캡 80→100,
#   4건 동시손절 최대손실 64→80USDT로 일일손실한도(100) 안쪽 유지.
# ★ 2026-08-12: 27건 시점 흐름이 좋아진 것 보고 사용자가 재차 확대 요청(25→30, 20%↑).
#   엔진상한 125USDT라 동시진입 5건→4건으로 줄지만 무리한 증액은 아님. 다만 이 시점의
#   증액 자체가 "좋은 결과 보고 사이즈 키우기" 패턴 — 51건 freeze 취지와 다소 배치되는
#   점은 기록해둠(would_change_log.md 참고).
FUT_MARGIN_PER_TRADE = 30.0

BUF_PATH = ROOT / "data" / "margin_short_buf.json"
POS_PATH = ROOT / "data" / "margin_short_pos.json"
TRADES_PATH = ROOT / "data" / "margin_short_trades.csv"
# ★ 2026-08-15: 엔진상한(캡)에 막혀 진입 못 한 신호를 "그림자 기록"으로 남김. 전략 로직은
#   전혀 건드리지 않고 관찰만 — 51건 도달 시 "캡 때문에 놓친 신호들이 실제로 얼마나 벌었을지"를
#   추측이 아니라 데이터로 판단하기 위함(에이전트 권고). 같은 심볼은 캡이 풀릴 때까지 매 사이클
#   반복 신호가 뜨므로 SHADOW_DEDUP_H 동안 1회만 기록.
SHADOW_PATH = ROOT / "data" / "margin_short_shadow.csv"
SHADOW_DEDUP_H = 6
_shadow_seen: dict[str, float] = {}
STRIKES_PATH = ROOT / "data" / "margin_short_coin_strikes.json"  # 코인별 연속 스탑 카운트
COOLDOWN_PATH = ROOT / "data" / "margin_short_cooldown.json"  # ★ 2026-07-22(감사 발견): 재시작 시
# cooldown이 메모리 전용이라 초기화되던 문제 — positions와 동일하게 디스크 영속화.

# ★ 2026-08-09: 신규상장 급등(TUTUSDT 2연패 계기) — 숏 대신 모의 롱으로 추적.
# 아직 검증 안 된 가설(상장빔은 되돌림 안 하고 계속 간다)이라 반드시 dry-run만, 실주문 절대 금지.
NEWLISTING_MAX_AGE_DAYS = 30      # 이보다 최근 상장이면 "신규상장 펌프"로 분류
NEWLISTING_LONG_MARGIN = MARGIN_PER_TRADE / 2
NEWLISTING_STOP_PCT = 17.5         # 숏(40%)보다 훨씬 타이트 — 상장빔 반전은 빠르고 격렬함
NEWLISTING_HOLD_H = 18             # 48h 아님 — 하이프는 빨리 식음
LISTING_AGE_CACHE_PATH = ROOT / "data" / "_listing_age_cache.json"
NEWLISTING_POS_PATH = ROOT / "data" / "newlisting_long_paper_pos.json"
NEWLISTING_TRADES_PATH = ROOT / "data" / "newlisting_long_paper_trades.csv"


def _listing_age_days(coin: str, cache: dict) -> float | None:
    """스팟 일봉 캔들 개수로 상장 이후 경과일 역산(바이낸스에 직접적인 상장일 필드가 없음).
    캐시 TTL 7일(경과일은 단조증가라 자주 다시 조회할 필요 없음)."""
    now = time.time()
    c = cache.get(coin)
    if c and now - c.get("ts", 0) < 7*24*3600:
        return c.get("age_days")
    try:
        r = requests.get(f"{BASE}/api/v3/klines", params={"symbol": f"{coin}USDT", "interval": "1d", "limit": 1000}, timeout=10)
        n = len(r.json()) if r.status_code == 200 else None
    except Exception:
        n = None
    if n is not None:
        cache[coin] = {"age_days": n, "ts": now}
    return n


def is_recent_listing(coin: str, cache: dict) -> bool:
    age = _listing_age_days(coin, cache)
    return age is not None and age < NEWLISTING_MAX_AGE_DAYS

# 유니버스: 바이낸스 마진 대출가능 코인 전체 (2026-07-11 확장 — 빗썸 교집합 제한 제거)
# ★ 발견1: 백테스트 314개 중 실제 빌릴 수 있는 건 절반뿐(급등 소형알트는 대출재고 없어 -3045 거부).
#   재검증: 엣지는 오히려 대출가능 쪽이 큼 → 대출가능만 감시.
# ★ 발견2: 빗썸 교집합으로 좁힐 이유 없음(거래는 바이낸스에서만 함). 제한 풀면 177→210개,
#   신호 1.8→3.2건/주로 78%↑, 승률76%·청산2%(오히려 개선). 단 신규분 TEST 수익은 약해
#   전체 TE +31%→+17%로 희석 — 기대치는 낮추되 표본이 2배라 실전검증이 빨라지는 게 더 중요.
BORROWABLE_PATH = ROOT / "data" / "_borrowable_all.txt"
BORROWABLE_REFRESH_H = 6

def refresh_borrowable():
    """바이낸스 마진 숏가능 + 실제 대출재고 있는 코인 전체 (klines 보유 여부 무관)."""
    from bithumb.margin_guard import _signed
    try:
        pairs = _signed("GET", "/sapi/v1/margin/allPairs").json()
        cands = sorted(set(p["symbol"].replace("USDT", "") for p in pairs
                           if p.get("quote") == "USDT" and p.get("isSellAllowed") and p.get("isMarginTrade")))
    except Exception as e:
        log.warning(f"마진쌍 조회 실패: {e}")
        try: notify.send(f"⚠️ 마진숏봇: 대출가능목록 갱신 실패 — {e} (IP차단·API권한 문제 의심)")
        except Exception: pass
        return []
    ok = []
    for coin in cands:
        try:
            r = _signed("GET", "/sapi/v1/margin/maxBorrowable", {"asset": coin})
            if r.status_code == 200 and float(r.json().get("amount", 0)) > 0:
                ok.append(coin)
        except Exception:
            pass
        time.sleep(0.1)
    if ok:
        BORROWABLE_PATH.write_text("\n".join(ok), encoding="utf-8")
        log.info(f"대출가능 유니버스 갱신: {len(ok)}/{len(cands)}개")
    return ok

def load_borrowable():
    try:
        return [c for c in BORROWABLE_PATH.read_text(encoding="utf-8").split() if c]
    except Exception:
        return []

UNIVERSE = load_borrowable()   # 비면 main()의 첫 refresh가 채움

# ★ 2026-07-21 선물 폴백 — 마진 대출재고 0으로 놓치던 코인(BANK·ACE류) 구제.
#   백테스트 확인(scratchpad, 문서화 예정): 선물은 반전구간 펀딩비 역풍으로 마진보다 비용은 더 들지만
#   여전히 순양수(TRAIN+2.17%/TEST+4.04% vs 마진+3.42%/+5.67%) — 대출 막힌 코인 전용 폴백으로만 사용,
#   대출 가능하면 항상 마진 우선(경제성 더 좋음).
FUTURES_ENGINE = "mshort_fut"
FUTURES_UNIVERSE_PATH = ROOT / "data" / "_futures_tradeable.txt"


def refresh_futures_tradeable():
    """바이낸스 선물(USDⓈ-M)에 상장된 코인 전체 — 마진 대출과 무관하게 항상 숏 가능."""
    try:
        r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=15)
        cands = sorted(set(s["symbol"].replace("USDT", "") for s in r.json()["symbols"]
                           if s["symbol"].endswith("USDT") and s.get("status") == "TRADING"
                           and s.get("contractType") == "PERPETUAL"))
    except Exception as e:
        log.warning(f"선물 심볼목록 조회 실패: {e}")
        return []
    if cands:
        FUTURES_UNIVERSE_PATH.write_text("\n".join(cands), encoding="utf-8")
        log.info(f"선물 유니버스 갱신: {len(cands)}개")
    return cands


def load_futures_tradeable():
    try:
        return set(c for c in FUTURES_UNIVERSE_PATH.read_text(encoding="utf-8").split() if c)
    except Exception:
        return set()


FUTURES_UNIVERSE = load_futures_tradeable()   # 비면 main()의 첫 refresh가 채움


def _load(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d
def _save(p, o):
    tmp = Path(p).with_suffix(".tmp"); tmp.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8"); tmp.replace(p)


def all_tickers():
    """전 심볼의 현재가 + 24h 변동률 + 24h 거래대금 (유동성 필터·1차 스크리닝용)."""
    r = requests.get(f"{BASE}/api/v3/ticker/24hr", timeout=15)
    r.raise_for_status()
    out = {}
    for x in r.json():
        try:
            out[x["symbol"]] = (float(x["lastPrice"]), float(x["priceChangePercent"]), float(x["quoteVolume"]))
        except Exception:
            pass
    return out


BTC_VOL_THRESHOLD = 3.26  # ★ 2026-08-07: 155건 백테스트 레짐분석 — BTC 24h 변동폭 중앙값(3.26%)
# 기준으로 나눠보니 평온장(≤중앙값) 승률70.9%·평균+8.36% vs 변동장(>중앙값) 승률59.3%·평균+0.04%
# (거의 본전). 학술연구(암호화폐 과잉반응 반전효과가 고변동성 시기엔 약화/역전)와 일치하는 패턴
# 확인 후 도입 — 변동장에서는 신규진입 자체를 보류.
_btc_vol_cache = {"pct": None, "ts": 0}


def btc_volatility_pct() -> float | None:
    """직전 24시간 BTC 변동폭(고가-저가)/시가 %. 5분 캐시(API 절약, 매 코인마다 안 부름)."""
    now = time.time()
    if _btc_vol_cache["pct"] is not None and now - _btc_vol_cache["ts"] < 300:
        return _btc_vol_cache["pct"]
    try:
        r = requests.get(f"{BASE}/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "5m", "limit": 288}, timeout=8)
        if r.status_code != 200:
            return _btc_vol_cache["pct"]
        k = r.json()
        if len(k) < 288:
            return _btc_vol_cache["pct"]
        hi = max(float(x[2]) for x in k)
        lo = min(float(x[3]) for x in k)
        op = float(k[0][1])
        pct = (hi - lo) / op * 100 if op > 0 else 0.0
        _btc_vol_cache["pct"] = pct
        _btc_vol_cache["ts"] = now
        return pct
    except Exception:
        return _btc_vol_cache["pct"]


def pump_6h(sym):
    """LOOKBACK_H시간 상승률 — 5분봉 LOOKBACK+1개 조회해 계산(함수명은 최초 6h 버전 잔재).
    (상승률, 현재가). 실패 시 (None, 0).
    ★ 이 시간대는 24h와 달리 API가 바로 안 주므로 klines 계산 필요. 후보에만 호출(1차 스크리닝 통과분)."""
    try:
        r = requests.get(f"{BASE}/api/v3/klines", params={"symbol": sym, "interval": "5m", "limit": LOOKBACK + 1}, timeout=8)
        if r.status_code != 200: return None, 0
        k = r.json()
        if len(k) < LOOKBACK + 1: return None, 0
        past = float(k[0][4]); cur = float(k[-1][4])
        if past <= 0: return None, 0
        return (cur / past - 1) * 100, cur
    except Exception:
        return None, 0


# ★ 2026-07-12 유동성 필터 완화 (200만 → 20만): 200만 필터는 대출가능 248개 중 56개만 통과시켜
#   실제 감시대상이 백테스트(237코인)의 1/4로 쪼그라들어 있었음 → 신호도 1/4로 줄어드는 구조적 누락.
#   20만으로 낮추면 204개 감시 = 백테스트와 유사. 체결·슬리피지는 명목 200 USDT 소액이라 문제없음.
MIN_QUOTE_VOL = 3_000_000   # 24h 거래대금 최소 300만 USDT (2026-08-08: 20만→300만, 저유동성/마이크로캡
                            # 숏스퀴즈 리스크 필터 강화 — ChatGPT/Perplexity/Manus/제미나이 4개 AI
                            # 공통 지적: DEXE/VIC/BICO/HFT/HEI 대형손실이 대부분 얇은 호가창 코인)
PRESCREEN_24H = 5.0         # 1차 스크리닝: 24h가 이 미만이면 klines 조회 생략(API 절약).
                            # ★ 2026-07-22(훅 지적으로 실측): "24h 낮으면 pump일 리 없다"는 가정은 거짓
                            # 케이스가 있음 — 7h+30% 신호 100건 표본 중 24h<15%가 8건(8%), 그중 6건은
                            # "이미 붕괴 후 반등"형(24h 자체가 -30~-86%인데 최근 7h만 급반등)이라 양수
                            # 문턱을 아무리 낮춰도 못 잡음(무필터 시에만 잡힘, 즉 사실상 필터 무의미화 필요).
                            # 15→5로 낮춰 근접 미스(HOME+14%,SLX+9%) 2건만 회수, 잔여 6%는 구조적 사각지대로
                            # 인지하고 수용(이 패턴은 신규펌프와 다른 성격이라 전략 취지상 배제도 무방할 수
                            # 있음 — 별도 검증 없이는 포함/배제 어느 쪽도 확정 못 함, 향후 과제).


TRADE_FIELDS = ["entry_time","exit_time","symbol","pump_2h","vol_mult",
                "entry_price","exit_price","margin_usdt","pnl_pct","pnl_usdt","live","reason",
                "btc_entry","btc_exit","mfe_pct","mae_pct","listing_age_days","qvol_24h"]


def log_trade(row):
    """★ 2026-08-16(사용자 요청): "이 종목이 확실한가"는 표본이 안 쌓이지만(종목당 1~4회뿐),
    "이런 특징의 코인이 잘 되는가"(신규상장 경과일·유동성 카테고리)는 여러 종목을 묶어서
    볼 수 있어 100~200건대에서 답이 나올 가능성이 큼 — 지금부터 메타데이터 축적.

    ★ 2026-08-20(기록감사 발견, 실거래 위험 수정): 이 함수에 예외처리가 없어서
    기록 실패가 호출부까지 전파됐음. 호출부(청산 처리)는 log_trade 20줄 뒤에
    del positions[sym]가 있어서, 여기서 예외가 나면 **거래소는 이미 청산됐는데
    봇은 계속 보유 중이라고 믿는** 상태가 됨(다음 사이클마다 already_closed 재시도).
    발생 조건이 특이하지 않음 — 사용자가 이 CSV를 엑셀로 열어두기만 해도
    PermissionError로 재현됨. 같은 파일의 log_shadow()에는 이미 예외처리가 있었는데
    정작 실거래 기록 쪽에만 없었음.

    기록은 잃더라도 포지션 상태는 지켜야 하므로 절대 예외를 올리지 않는다. 대신
    실패분을 별도 파일(_failed)에 덤프하고 텔레그램으로 알린다 — 조용히 사라지면
    원장대조에서 "봇 기록에 없는 거래"로만 나타나 원인 추적이 어렵기 때문."""
    try:
        # 헤더 필드수가 현재 스키마와 다르면(과거 필드 추가 시 헤더 미갱신) 컬럼이 밀림.
        # 2026-08-16 알트롱에서 실제 발생한 사고 — 여기서 먼저 감지해 경고만 남긴다.
        if TRADES_PATH.exists():
            with open(TRADES_PATH, encoding="utf-8") as f:
                head = f.readline().strip()
            if head and len(head.split(",")) != len(TRADE_FIELDS):
                log.error(f"★CSV 헤더 불일치: 파일 {len(head.split(','))}필드 vs "
                          f"코드 {len(TRADE_FIELDS)}필드 — 컬럼 밀림 상태로 기록 중")
        new = not TRADES_PATH.exists()
        with open(TRADES_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        log.error(f"★거래기록 실패({type(e).__name__}: {e}) — 포지션 정리는 계속 진행. "
                  f"실패분을 {TRADES_PATH.name}.failed 에 덤프")
        try:
            with open(str(TRADES_PATH) + ".failed", "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception:
            log.error(f"★덤프도 실패 — 유실된 거래: {row}")
        try:
            notify.send(f"🚨 거래기록 실패 {row.get('symbol')} — CSV가 열려있는지 확인 필요")
        except Exception:
            pass


def log_shadow(sym, pump_pct, price, blocked_by, open_exposure, cap):
    """★ 2026-08-15: 캡에 막혀 진입 못 한 신호 기록(순수 관찰, 주문 없음).
    51건 도달 시 '놓친 신호가 실제로 어떻게 됐을지'를 사후 검증하기 위한 데이터."""
    now = time.time()
    if now - _shadow_seen.get(sym, 0) < SHADOW_DEDUP_H * 3600:
        return
    _shadow_seen[sym] = now
    try:
        new = not SHADOW_PATH.exists()
        with open(SHADOW_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["signal_time", "symbol", "pump_pct", "signal_price",
                                               "blocked_by", "open_exposure", "cap"])
            if new: w.writeheader()
            w.writerow(dict(signal_time=datetime.now(KST).isoformat(), symbol=sym,
                            pump_pct=round(pump_pct, 1), signal_price=price, blocked_by=blocked_by,
                            open_exposure=round(open_exposure, 1), cap=cap))
    except Exception as e:
        log.warning(f"그림자기록 실패 {sym}: {e}")


def main():
    global UNIVERSE, FUTURES_UNIVERSE
    positions = _load(POS_PATH, {})
    cooldown = _load(COOLDOWN_PATH, {})
    now0 = time.time()
    cooldown = {k: v for k, v in cooldown.items() if v > now0}   # 만료된 항목 정리(파일 무한증가 방지)
    strikes = _load(STRIKES_PATH, {})
    listing_age_cache = _load(LISTING_AGE_CACHE_PATH, {})
    newlisting_positions = _load(NEWLISTING_POS_PATH, {})
    last_refresh = 0.0
    last_fut_refresh = 0.0
    last_capcfg_alert = 0.0   # ★ engine_caps_usdt 설정누락 알림 스팸방지용 타임스탬프
    last_regime_alert_ts = 0.0  # ★ 2026-08-07: 변동장 보류 로그 스팸방지용
    api_fail = 0   # ★ 마진잔고 조회 연속실패 카운터 — IP차단 등으로 조용히 0 반환되는 걸 감지·알림
    neg_balance_notified = False   # ★ 2026-07-22: 계좌 USDT 순자산이 마이너스(타 엔진 정상 차입)일 때 1회성 알림용
    ls = live_status()
    mode = "🔴실전" if (ls["enabled"] and ENGINE in ls["armed"]) else "🔵모의(dry)"
    _bal0 = get_margin_usdt()
    log.info(f"마진숏 트레이더 시작 [{mode}] — 대출가능 {len(UNIVERSE)}코인 + 선물폴백 {len(FUTURES_UNIVERSE)}코인, "
             f"{LOOKBACK_H}h+{PUMP_PCT:.0f}%급등→{HOLD_H}h숏+스탑{STOP_PCT:.0f}% "
             f"| 증거금상한 {ls['global_cap_usdt']}USDT {ls['leverage']}배 | 마진잔고 "
             f"{'조회실패' if _bal0 is None else f'{_bal0:.1f}'}")
    try: notify.send(f"📉 마진숏 트레이더 시작 [{mode}] — {LOOKBACK_H}h+{PUMP_PCT:.0f}% 급등주 숏, 대출가능 {len(UNIVERSE)}코인+선물폴백")
    except Exception: pass

    while True:
        try:
            now = time.time()
            tick = all_tickers()
            guard = MarginGuard(ENGINE)
            fut_guard = BinanceGuard(FUTURES_ENGINE)

            # ★ 2026-07-24: 포지션 점검(만기청산·손절)을 루프 맨 앞에서 최우선 처리 — 유니버스 갱신·신호탐지
            #   전부보다 먼저. rsi_extreme_short_paper.py가 07-16에 이미 겪고 고친 것과 동일한 버그가 이
            #   파일엔 이식이 안 돼 있었음. 특히 재시작 직후 첫 사이클은 대출가능 유니버스 전체 재조회
            #   (코인당 0.1초 슬립, 수백개면 수십초+)까지 겹쳐서 만기청산이 크게 밀릴 수 있었음 — 실제로
            #   워치독 5시간+ 다운 후 재기동 시 ERA가 48h 만기를 훌쩍 넘긴 채로 신호탐지·유니버스갱신이
            #   먼저 도는 동안 청산이 지연되는 걸 확인(이번엔 가격이 유리하게 움직여 손해는 없었음,
            #   수동청산으로 정리). 포지션 점검은 API콜이 열린 포지션 개수만큼(보통 0~1개)이라 거의
            #   즉시 끝남 — 나머지 무거운 작업보다 항상 먼저 돌게 둔다.
            for sym in list(positions.keys()):
                pos = positions[sym]
                t = tick.get(sym)
                px = t[0] if t else pos["entry_price"]
                # ★ 2026-07-27: 청산구조(트레일링·손절폭) 변경은 3개 AI(제미나이·챗GPT·마누스) 공통권고로
                #   "지금 표본(n=2)으론 시기상조, 표본 더 쌓고 절제백테 먼저"로 보류되어 MFE/MAE만 그림자
                #   기록해왔음. ★ 2026-08-10: 그 사이 실거래(COOKIE +6%→-25%, TST +24%→-4.5%)에서
                #   바로 그 우려(수익 줬다가 다 반납)가 실제로 재현됨 — 트레일링만 도입(손절폭 40%는
                #   미검증 상태 유지, 건드리지 않음). 최유리 15%p 도달 후 10%p 반납 시 즉시 청산.
                pos["mfe_price"] = min(pos.get("mfe_price", px), px)
                pos["mae_price"] = max(pos.get("mae_price", px), px)
                # ★ 2026-08-24: 마진 숏에 서버측 손절이 없던 구멍을 메움.
                #   2026-08-07 서버측 스탑 도입 때 **선물 숏**과 **마진 롱**만 커버되고
                #   **마진 숏**이 빠져 있었다(margin_guard엔 place_protective_stop_long만 존재).
                #   봇 5분 폴링(종가)만으론 봉내 급등을 못 잡아 손절선을 크게 뚫는다 —
                #   그림자함대 실측: TRUMPUSDT가 1.4h만에 +53.7% 급등, 손절선 +40%인데
                #   +53.73%에서 청산 = 증거금 기준 -107.65%. 보유가 빠를수록 초과분이 커진다.
                #   이미 열려 있던 무보호 포지션에도 소급 등록한다.
                #   ★ 이 주문은 아래 폴링 손절을 대체하지 않고 보강한다. 실패해도 폴링은 그대로 작동.
                if (SERVER_STOP_MARGIN
                        and pos.get("venue", "margin") == "margin" and pos.get("live")
                        and not pos.get("stop_order_id") and not pos.get("stop_giveup")
                        and px < pos["entry_price"] * (1 + STOP_PCT/100)):
                    try:
                        sres = guard.place_protective_stop_short(
                            pos["coin"], pos["qty"], pos["entry_price"] * (1 + STOP_PCT/100))
                    except Exception as e:
                        sres = {"error": str(e)}
                    if sres.get("deferred"):
                        # 거래소 가격필터로 아직 등록 불가(손절가가 현재가에서 너무 멂).
                        # 실패가 아니므로 카운트하지 않고 조용히 다음 사이클에 재시도한다.
                        pass
                    elif sres.get("live") and sres.get("verified"):
                        pos["stop_order_id"] = sres["order_id"]
                        pos.pop("stop_fails", None)
                        _save(POS_PATH, positions)
                        log.warning(f"★{sym} 서버측 숏스탑 소급 등록 orderId={sres['order_id']} @{sres['stop_price']:.6g}")
                        try: notify.send(f"🛡 {sym} 서버측 손절 등록 — 봇 다운 시에도 +{STOP_PCT:.0f}%에서 자동청산")
                        except Exception: pass
                    else:
                        fails = pos.get("stop_fails", 0) + 1
                        pos["stop_fails"] = fails
                        log.error(f"★{sym} 서버측 숏스탑 등록 실패({fails}회) → {sres}")
                        if fails == 1:
                            try: notify.send(f"⚠️ {sym} 서버측 손절 등록 실패 — 봇 폴링 손절만 작동 중")
                            except Exception: pass
                        if fails >= 5:
                            pos["stop_giveup"] = True   # 매 사이클 재시도로 API 낭비·레이트리밋 방지
                            log.error(f"★{sym} 서버측 숏스탑 5회 실패 — 재시도 중단(폴링 손절만 유효)")
                        _save(POS_PATH, positions)
                stop_hit = px >= pos["entry_price"] * (1 + STOP_PCT/100)
                cur_pnl_pct = (1 - px/pos["entry_price"]) * 100
                peak_pnl_pct = (1 - pos["mfe_price"]/pos["entry_price"]) * 100
                trail_hit = peak_pnl_pct >= TRAIL_TRIGGER_PCT and cur_pnl_pct <= peak_pnl_pct - TRAIL_GIVEBACK_PCT
                if not stop_hit and not trail_hit and now < pos["exit_ts"]:
                    continue
                reason = f"스탑+{STOP_PCT:.0f}%" if stop_hit else (f"트레일링(최고{peak_pnl_pct:.0f}%→{cur_pnl_pct:.0f}%)" if trail_hit else f"{HOLD_H}h만기")
                venue = pos.get("venue", "margin")   # 옛 포지션(필드 없음) = 마진으로 취급(원래 유일 경로였음)
                if venue == "futures":
                    cres = fut_guard.close_short_futures(pos["coin"], stop_order_id=pos.get("stop_order_id"))
                    lev = load_futures_config().get("leverage", 2)
                    venue_tag = "선물"
                else:
                    # ★ 2026-08-24: 서버측 숏스탑 취소(고아주문 방지) + 이미 그 스탑이 체결됐으면
                    #   already_closed 로 받아 무한 재시도를 막는다(선물 경로와 동일 패턴).
                    cres = guard.close_short(pos["coin"], stop_order_id=pos.get("stop_order_id"))
                    lev = load_config().get("leverage", 2)
                    venue_tag = "마진"
                # ★ 실전 포지션은 실제 청산(live) 확인 전엔 로컬에서 지우지 않음.
                #   과거 버그: 청산주문이 실패(API장애·IP차단 등)해도 무조건 positions에서 삭제해
                #   실제 거래소엔 레버리지 숏이 그대로 열려있는데 봇은 더 이상 스탑/만기를 감시 안 함.
                if pos["live"] and not cres.get("live"):
                    fails = pos.get("close_fails", 0) + 1
                    pos["close_fails"] = fails
                    log.error(f"★{venue_tag}청산 실패(포지션 유지, 다음루프 재시도) {sym} {reason} → {cres} (연속{fails}회)")
                    if fails in (1, 3) or fails % 10 == 0:
                        try: notify.send(f"🚨 {venue_tag}숏 청산 실패 {sym} {reason} → {cres} (연속{fails}회) — 실거래소엔 포지션 열려있음! 확인 필요")
                        except Exception: pass
                    continue
                # ★ 2026-08-07: 서버측 스탑이 봇보다 먼저 트리거된 경우(already_closed) — 실제
                #   체결가를 알 수 있으면 그걸로, 모르면 현재가로 pnl 기록. "청산 실패"로 오인해
                #   무한 재시도하던 기존 버그 수정(위 close_fails 분기를 안 타도록 already_closed는
                #   cres.get("live")가 True라 위에서 이미 통과됨).
                if cres.get("already_closed"):
                    reason = f"서버측{reason}(다운중자동실행)"
                    if cres.get("exit_price"):
                        px = cres["exit_price"]
                pnl_pct = (1 - px/pos["entry_price"])*100
                pnl_usdt = pos["margin"] * lev * (pnl_pct/100)
                if pos["live"]:
                    (fut_guard if venue == "futures" else guard).record_realized(pnl_usdt)
                btc_exit = tick.get("BTCUSDT", (None,))[0]
                mfe_price = pos.get("mfe_price", pos["entry_price"])
                mae_price = pos.get("mae_price", pos["entry_price"])
                mfe_pct = round((1 - mfe_price/pos["entry_price"])*100, 2)   # 최대유리변동(숏이라 가격하락이 유리)
                mae_pct = round((mae_price/pos["entry_price"] - 1)*100, 2)   # 최대불리변동(가격상승이 불리)
                log_trade(dict(entry_time=pos["entry_iso"], exit_time=datetime.now(KST).isoformat(), symbol=sym,
                               pump_2h=pos["pump"], vol_mult=pos["vr"], entry_price=pos["entry_price"], exit_price=px,
                               margin_usdt=pos["margin"], pnl_pct=round(pnl_pct,2), pnl_usdt=round(pnl_usdt,2),
                               live=pos["live"], reason=f"{reason}[{venue_tag}]",
                               btc_entry=pos.get("btc_entry"), btc_exit=btc_exit,
                               mfe_pct=mfe_pct, mae_pct=mae_pct,
                               listing_age_days=pos.get("listing_age_days"), qvol_24h=pos.get("qvol_24h")))
                log.warning(f"★{venue_tag}숏 청산 {sym} @{px:g} {reason} pnl={pnl_pct:+.2f}%({pnl_usdt:+.2f}USDT) → {cres.get('live') and '실청산' or cres}")
                try: notify.send(f"📈 {venue_tag}숏 청산 {sym} {reason} pnl={pnl_pct:+.1f}% ({pnl_usdt:+.1f}USDT)")
                except Exception: pass
                # ★ 2026-08-09: 코인별 연속 스탑 카운트 — 2연속이면 7일 블랙리스트(TUTUSDT 2연패 계기)
                coin_key = pos["coin"]
                if stop_hit:
                    strikes[coin_key] = strikes.get(coin_key, 0) + 1
                    if strikes[coin_key] >= 2:
                        cooldown[sym] = now + STRIKE_BLACKLIST_H * 3600
                        log.warning(f"★{coin_key} 연속 {strikes[coin_key]}회 스탑 → 7일 블랙리스트")
                        try: notify.send(f"⛔ {coin_key} 연속 {strikes[coin_key]}회 손절 — 7일간 신규진입 제외")
                        except Exception: pass
                else:
                    strikes[coin_key] = 0
                del positions[sym]

            _save(POS_PATH, positions)
            _save(STRIKES_PATH, strikes)

            # ★ 2026-08-09: 신규상장 모의 롱 청산 점검 (dry-run 전용, 실주문 없음)
            for nsym in list(newlisting_positions.keys()):
                npos = newlisting_positions[nsym]
                nt = tick.get(nsym)
                npx = nt[0] if nt else npos["entry_price"]
                stop_hit = npx <= npos["entry_price"] * (1 - NEWLISTING_STOP_PCT/100)
                expired = now >= npos["exit_ts"]
                if not stop_hit and not expired:
                    continue
                nreason = f"스탑-{NEWLISTING_STOP_PCT:.0f}%" if stop_hit else f"{NEWLISTING_HOLD_H}h만기"
                npnl_pct = (npx/npos["entry_price"] - 1)*100
                nnew = not NEWLISTING_TRADES_PATH.exists()
                with open(NEWLISTING_TRADES_PATH, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=["entry_time","exit_time","symbol","pump_2h","entry_price","exit_price","pnl_pct","reason"])
                    if nnew: w.writeheader()
                    w.writerow(dict(entry_time=npos["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                                     symbol=nsym, pump_2h=npos["pump"], entry_price=npos["entry_price"],
                                     exit_price=npx, pnl_pct=round(npnl_pct,2), reason=nreason))
                log.info(f"[모의:신규상장롱] {nsym} @{npx:g} {nreason} pnl={npnl_pct:+.2f}%(모의, 실주문없음)")
                del newlisting_positions[nsym]
            _save(NEWLISTING_POS_PATH, newlisting_positions)

            # ★ 마진잔고 헬스체크. 2026-07-22: get_margin_usdt()가 이제 API실패 시 None(0.0과 구분)을
            #   반환하도록 수정됨 — 예전엔 이 함수가 실패해도 조용히 0.0을 반환해 "마이너스 잔고(타 엔진
            #   정상 차입)"와 "진짜 API장애"를 구분 못 하고 216회 연속 "IP차단 의심" 오진 알림을 보낸 사건
            #   있었음. 이제 None 자체로 명확히 구분. 신규진입 사이징은 더 이상 이 잔고에 의존하지 않음
            #   (MARGIN_PER_TRADE 고정값 사용, 아래 참조) — 여긴 순수 관측용.
            bal = get_margin_usdt()
            if bal is None:
                api_fail += 1
                if api_fail in (2, 6) or api_fail % 12 == 0:
                    log.error(f"마진잔고 조회 {api_fail}회 연속 실패 — API장애 의심(자세한 원인은 margin_guard.log 참조)")
                    try: notify.send(f"🚨 마진숏봇: 마진잔고 조회 {api_fail}회 연속 실패 — API 문제 의심, 확인 필요")
                    except Exception: pass
            else:
                if api_fail >= 2:
                    try: notify.send(f"✅ 마진숏봇: API 정상화 (잔고 {bal:.1f} USDT)")
                    except Exception: pass
                api_fail = 0
                if bal < 0 and not neg_balance_notified:
                    log.info(f"마진잔고 {bal:.1f}(마이너스) — 타 엔진 차입 추정, 정상. 신규진입은 고정금액 사용")
                    try: notify.send(f"ℹ️ 마진숏봇: 계좌 USDT 순자산 마이너스({bal:.1f}) — 타 엔진(재량롱 등) 정상 차입으로 추정, 신규진입은 고정금액 사용해 영향 없음")
                    except Exception: pass
                    neg_balance_notified = True
                elif bal >= 0:
                    neg_balance_notified = False

            # ★ 엔진상한 설정 유효성 — 루프 밖에서 사이클당 1회만 확인(코인마다 반복하면 알림 폭주)
            engine_caps = load_config().get("engine_caps_usdt", {})
            if ENGINE not in engine_caps:
                log.error(f"설정오류: engine_caps_usdt에 {ENGINE} 없음 — 신규진입 전면 차단(안전상 fail-closed)")
                if now - last_capcfg_alert >= 1800:   # 30분에 한 번만 알림(스팸 방지)
                    try: notify.send(f"🚨 마진숏봇: engine_caps_usdt에 {ENGINE} 설정 없음 — 신규진입 전면 차단 중, margin_live_config.json 확인 필요")
                    except Exception: pass
                    last_capcfg_alert = now
                engine_caps = None   # 아래 루프에서 신규진입 전부 스킵시킬 신호

            # 선물 유니버스 주기 갱신 (마진 대출과 무관 — 상장폐지/신규상장 정도만 반영하면 됨)
            if now - last_fut_refresh >= BORROWABLE_REFRESH_H * 3600:
                last_fut_refresh = now
                fresh_fut = refresh_futures_tradeable()
                if fresh_fut: FUTURES_UNIVERSE = set(fresh_fut)
            # 대출가능 유니버스 주기 갱신 (재고가 수시로 바뀜 → 못 빌리는 코인에 주문 던지는 것 방지)
            if now - last_refresh >= BORROWABLE_REFRESH_H * 3600:
                last_refresh = now
                fresh = refresh_borrowable()
                if fresh: UNIVERSE = fresh

            # 1) 신호 탐지 — LOOKBACK_H시간 +PUMP_PCT% 급등 (거래량 필터 없음: 검증 결과 불필요)
            #    1차: 24h 변동률로 후보 추림(PRESCREEN_24H, klines 조회 절약용 근사치일 뿐 —
            #    정확한 하한 보장 아님, 상세는 PRESCREEN_24H 정의부 주석) → 2차: 후보만 5분봉으로
            #    LOOKBACK_H시간 정밀계산
            # ★ 2026-07-21: 대출가능(UNIVERSE) ∪ 선물상장(FUTURES_UNIVERSE) 전체 스캔.
            #   대출가능하면 마진 우선(경제성 더 좋음, 백테스트 확인), 대출 안 되고 선물만 있으면 폴백.
            UNIVERSE_SET = set(UNIVERSE)
            fut_cfg = load_futures_config()
            fut_caps = fut_cfg.get("engine_caps_usdt", {})
            # ★ 2026-08-07: 변동장(BTC 24h변동폭>3.26%)이면 신규진입 전면 보류 — 레짐분석 근거는
            # BTC_VOL_THRESHOLD 정의부 주석 참조. 기존 포지션 청산 로직(위쪽)은 그대로 작동.
            btc_vol = btc_volatility_pct()
            regime_blocked = btc_vol is not None and btc_vol > BTC_VOL_THRESHOLD
            if regime_blocked and now - last_regime_alert_ts > 1800:
                log.info(f"변동장 감지(BTC 24h변동 {btc_vol:.2f}%>{BTC_VOL_THRESHOLD}%) — 신규진입 전면 보류")
                last_regime_alert_ts = now
            for coin in (UNIVERSE_SET | FUTURES_UNIVERSE):
                if regime_blocked:
                    break
                sym = f"{coin}USDT"
                t = tick.get(sym)
                if not t: continue
                px, chg24, qvol = t
                if px <= 0 or qvol < MIN_QUOTE_VOL: continue
                if sym in positions or cooldown.get(sym, 0) > now:
                    continue
                if chg24 < PRESCREEN_24H:      # 1차 스크리닝 (klines 조회 절약)
                    continue
                ret6h, px6 = pump_6h(sym)      # 2차 정밀 — LOOKBACK_H시간 상승률
                if ret6h is None or ret6h < PUMP_PCT or ret6h >= PUMP_PCT_MAX:
                    continue
                if px6 > 0: px = px6
                ret2h = ret6h   # 기록용(LOOKBACK_H시간 상승률)
                vr = 0.0

                # ★ 2026-08-09: 신규상장 급등은 되돌림 논리가 안 맞음(TUTUSDT 2연패 계기, 상장빔은
                # 하이프성이라 계속 갈 수 있음) — 숏 스킵하고 대신 모의 롱만 기록(실주문 없음, dry-run).
                if is_recent_listing(coin, listing_age_cache):
                    if sym not in newlisting_positions and len(newlisting_positions) < 10:
                        newlisting_positions[sym] = {
                            "coin": coin, "entry_price": px, "pump": round(ret6h,1),
                            "entry_iso": datetime.now(KST).isoformat(),
                            "exit_ts": now + NEWLISTING_HOLD_H*3600,
                        }
                        log.info(f"[모의:신규상장롱] {sym} {LOOKBACK_H}h+{ret6h:.0f}% 신규상장 감지 → 숏 스킵, 모의롱 진입(실주문없음)")
                    continue

                use_margin = coin in UNIVERSE_SET
                if use_margin:
                    # 누적 노출 상한 확인 (48h 홀딩이라 동시다발 진입 가능 → 엔진 자체상한 초과 방지)
                    # ★ 2026-07-13 버그수정: global_cap_usdt(엔진 3개 합산 180)로 체크하고 있어서
                    #   mshort 혼자 180까지 쌓일 수 있었음(자기 엔진상한 100을 무시) → 자기 엔진상한으로 교체.
                    #   설정유효성(engine_caps_usdt에 ENGINE 존재하는지)은 루프 진입 전에 한 번만 확인함(위쪽).
                    if engine_caps is None:
                        continue   # 설정오류로 이번 사이클은 신규진입 전면 스킵(알림은 위에서 사이클당 1회만 이미 보냄)
                    open_margin = sum(p["margin"] for p in positions.values() if p.get("venue", "margin") == "margin")
                    ecap = engine_caps[ENGINE]
                    # ★ 2026-07-22: MARGIN_PER_TRADE를 ecap과 무관한 고정값으로 그대로 쓰면, 나중에 누가
                    #   engine_caps_usdt.mshort를 100 미만으로 바꿀 경우 선물폴백(fcap=50)때와 똑같이
                    #   이 분기가 영원히 막히는 버그가 재발할 수 있음 — 항상 ecap 기준으로 클램프.
                    trade_margin = min(MARGIN_PER_TRADE, ecap)
                    if open_margin + trade_margin > ecap:
                        log.info(f"진입 보류 {sym}({LOOKBACK_H}h+{ret6h:.0f}%): 누적노출 {open_margin:.0f}+{trade_margin:.0f}>엔진상한 {ecap}")
                        continue
                    # ★ 2026-07-22: get_margin_usdt()(계좌 전체 USDT 순자산)로 min() 클램프하던 걸 제거.
                    #   manuallong 등 타 엔진이 USDT를 정상 차입하면 이 값이 마이너스가 될 수 있는데,
                    #   min()이 그 마이너스를 그대로 골라 notional이 음수가 되고 조용히 진입 실패하는
                    #   버그가 있었음(실제로 ONEUSDT 신호를 이렇게 놓침). 진짜 잔고부족은 바이낸스가
                    #   API 레벨에서 거부하며 이미 로그·원장기록됨 — 여기선 고정금액만 사용.
                    margin = trade_margin
                    res = guard.open_short(coin, margin)
                    cooldown[sym] = now + COOLDOWN_H*3600
                    if res.get("live"):
                        positions[sym] = {"coin": coin, "entry_ts": now, "entry_price": res.get("price", px),
                                          "qty": res["qty"], "margin": margin, "venue": "margin",
                                          "pump": round(ret2h,1), "vr": round(vr,1),
                                          "exit_ts": now + HOLD_H*3600, "entry_iso": datetime.now(KST).isoformat(), "live": True,
                                          "btc_entry": tick.get("BTCUSDT", (None,))[0],
                                          "listing_age_days": _listing_age_days(coin, listing_age_cache), "qvol_24h": round(qvol)}
                        # ★ 2026-08-24: 진입 직후 서버측 손절 등록 — 선물 경로와 같은 보호수준으로 맞춤.
                        #   실패해도 포지션은 유지되고 봇 폴링 손절이 계속 작동한다(무보호 아님).
                        sres = {"skip": "SERVER_STOP_MARGIN=False"}
                        if SERVER_STOP_MARGIN:
                            try:
                                sres = guard.place_protective_stop_short(
                                    coin, res["qty"], positions[sym]["entry_price"] * (1 + STOP_PCT/100))
                            except Exception as e:
                                sres = {"error": str(e)}
                        if not SERVER_STOP_MARGIN or sres.get("deferred"):
                            # deferred = 거래소 가격필터로 아직 등록 불가. 포지션 감시 루프가
                            # 가격이 손절선에 접근하면 자동으로 다시 시도한다.
                            pass
                        elif sres.get("live") and sres.get("verified"):
                            positions[sym]["stop_order_id"] = sres["order_id"]
                        else:
                            log.error(f"🚨 {sym} 서버측 숏스탑 등록 실패 — 봇 폴링 손절만 작동 → {sres}")
                            try: notify.send(f"🚨 {sym} 마진숏 서버측 손절 등록 실패 — 봇 폴링만 유효, 확인 필요")
                            except Exception: pass
                        log.warning(f"★실전 마진숏 진입 {sym} {LOOKBACK_H}h+{ret2h:.0f}% 증거금{margin:.0f} → {res['qty']}개 (서버스탑={positions[sym].get('stop_order_id')})")
                        try: notify.send(f"📉 마진숏 진입 {sym} {LOOKBACK_H}h+{ret2h:.0f}% (증거금{margin:.0f}USDT)")
                        except Exception: pass
                    else:
                        log.info(f"마진 진입 dry/실패 {sym}: {res}")
                else:
                    # ★ 선물 폴백: 마진 대출재고 없는 코인(BANK·ACE류) 전용. FUTURES_ENGINE 미설정/미arm이면 자동 dry.
                    if FUTURES_ENGINE not in fut_caps:
                        continue   # 선물폴백 미설정 — 조용히 스킵(마진과 별개 기능이라 사이클마다 알림 안 보냄)
                    open_fut = sum(p["margin"] for p in positions.values() if p.get("venue") == "futures")
                    fcap = fut_caps[FUTURES_ENGINE]
                    # ★ 2026-07-22 발견(사용자 지적): MARGIN_PER_TRADE(마진용 100)를 선물폴백 사이징에도
                    #   그대로 써서 fcap(mshort_fut 캡 50)보다 항상 커, 이 분기가 구조적으로 절대 통과할
                    #   수 없었음 — ERAUSDT가 07-21 10:26~15:40 5시간+ 동안 6h+40~85%로 계속 신호를
                    #   냈는데도 매번 "누적노출 0+100>엔진상한 50"으로 전부 놓침(mshort 실전 0건의
                    #   핵심 원인). 선물폴백 전용 사이징을 fcap 기준으로 별도 계산.
                    fut_margin = min(FUT_MARGIN_PER_TRADE, fcap)
                    if open_fut + fut_margin > fcap:
                        log.info(f"선물폴백 진입 보류 {sym}({LOOKBACK_H}h+{ret6h:.0f}%): 누적노출 {open_fut:.0f}+{fut_margin:.0f}>엔진상한 {fcap}")
                        log_shadow(sym, ret6h, px, "engine_cap", open_fut, fcap)
                        continue
                    # ★ 2026-07-22: 마진 경로와 동일 이유로 get_futures_usdt() min() 클램프 제거.
                    #   선물지갑은 manuallong과 무관한 별도 지갑이라 마이너스가 될 일은 없지만, API
                    #   실패 시 0.0을 반환하는 동일 패턴이 있어 똑같이 조용한 실패로 이어질 수 있었음.
                    #   진짜 잔고부족은 open_short_futures() 내부에서 거래소가 거부하며 로그됨.
                    margin = fut_margin
                    # ★ 2026-08-07: stop_pct 전달 — 진입 직후 거래소 서버측 STOP_MARKET 보호주문
                    #   같이 등록(컴퓨터/봇 다운 시에도 손절 실행 보장, 3개 AI 교차검증 후 도입).
                    res = fut_guard.open_short_futures(coin, margin, stop_pct=STOP_PCT)
                    cooldown[sym] = now + COOLDOWN_H*3600
                    if res.get("live"):
                        positions[sym] = {"coin": coin, "entry_ts": now, "entry_price": res.get("price", px),
                                          "qty": res["qty"], "margin": margin, "venue": "futures",
                                          "pump": round(ret2h,1), "vr": round(vr,1),
                                          "exit_ts": now + HOLD_H*3600, "entry_iso": datetime.now(KST).isoformat(), "live": True,
                                          "btc_entry": tick.get("BTCUSDT", (None,))[0],
                                          "stop_order_id": res.get("stop_order_id"),
                                          "listing_age_days": _listing_age_days(coin, listing_age_cache), "qvol_24h": round(qvol)}
                        if not res.get("stop_verified"):
                            log.error(f"🚨 {sym} 서버측 스탑주문 검증 실패 — 무보호 상태일 수 있음, 수동 확인 필요")
                            # ★ 2026-08-20(기록감사 발견): 위 log.error는 로그파일에만 남고
                            # 아래 텔레그램 메시지는 항상 📉라 화이트리스트를 통과 못 했음
                            # (quiet_hours 여부와 무관하게 이 알림 자체가 24시간 도달 불가였음).
                            # 서버측 손절 없이 열린 포지션이라 이걸 놓치면 봇 감시에만
                            # 의존하게 되므로, 🚨로 별도 발송(quiet_hours 무시하고 항상 감).
                            try: notify.send(f"🚨 {sym} 서버측 스탑 등록 실패 — 무보호 포지션, 수동 확인 필요")
                            except Exception: pass
                        log.warning(f"★실전 선물숏 진입(마진대출폴백) {sym} {LOOKBACK_H}h+{ret2h:.0f}% 증거금{margin:.0f} → {res['qty']}개 (서버스탑={res.get('stop_order_id')})")
                        try: notify.send(f"📉 선물숏 진입(마진폴백) {sym} {LOOKBACK_H}h+{ret2h:.0f}% (증거금{margin:.0f}USDT, 서버스탑{'OK' if res.get('stop_verified') else '실패!'})")
                        except Exception: pass
                    else:
                        log.info(f"선물 진입 dry/실패 {sym}: {res}")

            _save(POS_PATH, positions)
            # ★ 2026-07-22(감사 발견): cooldown이 메모리 전용이라 재시작 시 초기화 → 청산 직후 재시작되면
            #   12h 재진입 쿨다운 없이 즉시 재진입 가능했음. positions와 동일하게 매 사이클 디스크 영속화
            #   + 만료분은 저장 전에 정리(파일 무한증가 방지).
            # 참고: 이 정리는 파일 용량 관리를 위한 하우스키핑일 뿐 — 실제 쿨다운 적용 여부는
            # 신호탐지 루프에서 이번 사이클의 now로 이미 판정 끝남(cooldown.get(sym,0) > now), 무관.
            cooldown = {k: v for k, v in cooldown.items() if v > time.time()}
            _save(COOLDOWN_PATH, cooldown)
            _save(LISTING_AGE_CACHE_PATH, listing_age_cache)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
