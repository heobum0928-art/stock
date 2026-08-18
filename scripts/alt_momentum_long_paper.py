"""
알트 모멘텀 롱 모의검증기 (alt_momentum_long_paper) — 순수 모의, 매매 API 미호출.

배경(2026-08-17): margin_short(숏)는 51건 동결검증 거의 끝나가는데, 롱 쪽은
hybrid_trader/core_trader/core_leveraged 전부 "BTC>200일선"이라는 강세장 게이트에
막혀 8/15부터 지금까지 단 1건도 진입을 못 함(BTC 자체가 계속 약세라 신호가 안 뜸).
BTC 규모의 추세전환은 그 자체로 실전화 트랙(core_trader/core_leveraged)에 맡기고,
이 봇은 그 게이트를 빼고 "알트 모멘텀 Top3" 선별 로직만 상시 가동해서 지금 당장
포워드 데이터를 쌓기 시작한다(100건 목표). hybrid_trader.py의 rank_alts()와 동일
로직(20일 모멘텀 상위 3개, 유동성 플로어) 재사용 — 단 hybrid_trader는 포트폴리오
비중조절 방식이라 "거래 1건"이 안 잡히므로, margin_short류 파일들과 동일하게
개별 코인 단위 진입/청산을 기록하는 구조로 새로 작성.

청산 규칙(margin_short의 숏 로직을 롱으로 대칭 적용 + 모멘텀 고유 조건 추가):
  - 스탑: -20% (숏의 -40%보다 타이트 — 모멘텀 롱은 반대방향 손실이 더 빨리 뼈아픔)
  - 트레일링: +20% 도달 시 무장, 최고가 대비 10% 반납 시 청산(숏의 "pnl %p 기준 반납"과
    달리 "고점가격 대비 %" 기준이라 수치는 다름 — 버그헌터 감사로 확인, 동작은 의도대로임)
  - 랭크아웃: 일일 리랭크 때 Top3 모멘텀에서 탈락하면 즉시 청산(모멘텀 논리 무효화)
  - 최대보유: 21일(숏 48h보다 훨씬 긺 — 일봉 신호 기반 전략이라 스케일이 다름)

가격은 candles_daily의 최신 일봉 종가 사용(hybrid_trader와 동일 소스) — 그 데이터
자체가 6시간마다(CoinbaseDailyCandleUpdate) 갱신되므로 이 봇의 폴링 주기도 6시간으로
맞춤. 인트라데이 정밀도는 없지만, 애초에 "일봉 모멘텀" 전략이라 그걸로 충분.

★ 순수 모의: 매매 API 미호출. 포트 47256.
상태 data/alt_momentum_long_pos.json | 기록 data/alt_momentum_long_trades.csv
로그 logs/alt_momentum_long_paper.log
Run: python scripts/alt_momentum_long_paper.py
"""
import sys, atexit, time, json, csv, glob, os, socket, logging
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
    try: _sock.bind(("127.0.0.1", 47256))
    except OSError: print("[ERROR] alt_momentum_long_paper 이미 실행 중 (포트 47256)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ALTLONG] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/alt_momentum_long_paper.log", encoding="utf-8")])
log = logging.getLogger(__name__)

DAILY_DIR = ROOT / "data" / "candles_daily"
POS_PATH = ROOT / "data" / "alt_momentum_long_pos.json"
TRADES_PATH = ROOT / "data" / "alt_momentum_long_trades.csv"

# hybrid_trader.py와 동일(비교 가능하게 그대로 재사용)
ALT_N = 3
MOM_LB = 20
LIQ_FLOOR = 100_000_000
CHECK_SEC = 21600   # 6시간 — candles_daily 자체 갱신주기(CoinbaseDailyCandleUpdate)와 일치

# 이 봇 고유 청산 규칙(margin_short 숏 로직을 롱으로 대칭 적용)
STOP_PCT = 20.0
TRAIL_TRIGGER_PCT = 20.0
TRAIL_GIVEBACK_PCT = 10.0
MAX_HOLD_DAYS = 21
NOTIONAL_USDT = 30.0   # 다른 모의봇들과 동일 단위(margin 개념 아님, 순수 명목 포지션 크기)


def _load(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d
def _save(p, o):
    tmp = Path(p).with_suffix(".tmp"); tmp.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(p)


def _closes(ticker: str) -> list[float] | None:
    f = DAILY_DIR / f"{ticker}_1d.json"
    if not f.exists(): return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return [float(x["trade_price"]) for x in d]
    except Exception:
        return None


def _liq_ok(ticker: str) -> bool:
    f = DAILY_DIR / f"{ticker}_1d.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        vols = [float(x.get("candle_acc_trade_price", 0)) for x in d[-MOM_LB:]]
        return len(vols) >= MOM_LB and sum(vols) / len(vols) >= LIQ_FLOOR
    except Exception:
        return False


# ★ 2026-08-17: update_daily_candles.py 로그에서 ES/H/HIGH/IP/OXT 등 여러 코인이 빗썸
# 상장폐지/티커변경으로 몇 주~두 달째 갱신 실패 중인 걸 발견 — candles_daily/*.json엔
# 옛 데이터가 그대로 남아있어서, 그 정지된 시점에 우연히 큰 상승이 있었으면 모멘텀랭킹에
# "죽은 코인"이 잘못 뽑힐 위험이 있음. 최신 캔들이 STALE_DAYS 이내가 아니면 후보에서 제외.
STALE_DAYS = 2


def _is_stale(ticker: str) -> bool:
    f = DAILY_DIR / f"{ticker}_1d.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not d: return True
        last = datetime.fromisoformat(d[-1]["candle_date_time_kst"]).replace(tzinfo=KST)
        return (datetime.now(KST) - last) > timedelta(days=STALE_DAYS)
    except Exception:
        return True


def rank_alts() -> list[tuple[str, float]]:
    """20일 모멘텀 상위 ALT_N 알트(유동성 플로어 통과, 최근 갱신됨, BTC 제외). [(ticker, mom_pct), ...] 반환."""
    scored = []
    for f in glob.glob(str(DAILY_DIR / "*_1d.json")):
        t = os.path.basename(f).replace("_1d.json", "")
        if t == "BTC": continue
        if _is_stale(t): continue
        cl = _closes(t)
        if not cl or len(cl) < MOM_LB + 1: continue
        if not _liq_ok(t): continue
        mom = (cl[-1] / cl[-1 - MOM_LB] - 1) * 100
        scored.append((mom, t))
    scored.sort(reverse=True)
    return [(t, mom) for mom, t in scored[:ALT_N]]


def latest_price(ticker: str) -> float:
    cl = _closes(ticker)
    return cl[-1] if cl else 0.0


def btc_mom_pct() -> float | None:
    """BTC의 동일 20일 모멘텀 — 판단(entry/exit)엔 안 쓰고 로그에만 남김(margin_short의
    btc_entry/btc_exit와 동일 패턴). 표본 쌓이면 '코인모멘텀-BTC모멘텀=상대강도' 사후분석용
    (버그헌터 에이전트 권고, 2026-08-18 — ACE가 모멘텀1위였는데도 스탑맞은 사례 계기)."""
    cl = _closes("BTC")
    if not cl or len(cl) < MOM_LB + 1:
        return None
    return (cl[-1] / cl[-1 - MOM_LB] - 1) * 100


def log_trade(row):
    new = not TRADES_PATH.exists()
    with open(TRADES_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["entry_time", "exit_time", "symbol", "entry_price", "exit_price",
                                           "mom_pct_at_entry", "btc_mom_pct_at_entry", "notional_usdt",
                                           "pnl_pct", "pnl_usdt", "reason", "mfe_pct", "mae_pct"])
        if new: w.writeheader()
        w.writerow(row)


def main():
    positions = _load(POS_PATH, {})
    log.info(f"알트모멘텀 롱 모의검증 시작 — Top{ALT_N}(모멘텀{MOM_LB}일,유동성플로어) 상시가동(BTC강세게이트 없음) | "
              f"스탑-{STOP_PCT:.0f}% / 트레일+{TRAIL_TRIGGER_PCT:.0f}%→{TRAIL_GIVEBACK_PCT:.0f}%p반납 / "
              f"랭크아웃청산 / 최대{MAX_HOLD_DAYS}일 | 순수모의(매매0)")
    try:
        from bithumb import notify
        notify.send(f"🌱 알트모멘텀 롱 모의검증 시작 — hybrid_trader 알트선별로직, BTC게이트 없이 상시가동, 100건 목표")
    except Exception: pass

    last_rerank_date = None

    while True:
        try:
            now = time.time()
            today = datetime.now(KST).date().isoformat()

            # 1) 포지션 점검(청산) — 매 사이클
            if positions:
                current_top = None  # 필요할 때만 계산(랭크아웃 체크용)
                for sym in list(positions.keys()):
                    pos = positions[sym]
                    px = latest_price(pos["coin"])
                    if px <= 0:
                        continue
                    pos["max_p"] = max(pos["max_p"], px)   # 롱이라 유리한 방향=상승
                    pos["min_p"] = min(pos["min_p"], px)
                    entry = pos["entry_price"]
                    favorable_pct = (pos["max_p"] / entry - 1) * 100
                    pnl = (px / entry - 1) * 100
                    hold_days = (now - pos["entry_ts"]) / 86400

                    reason = None
                    if px <= entry * (1 - STOP_PCT / 100):
                        reason = f"스탑-{STOP_PCT:.0f}%"
                    elif favorable_pct >= TRAIL_TRIGGER_PCT:
                        trail_level = pos["max_p"] * (1 - TRAIL_GIVEBACK_PCT / 100)
                        if px <= trail_level:
                            reason = f"트레일(최고{favorable_pct:.0f}%→{pnl:.0f}%)"
                    if reason is None and hold_days >= MAX_HOLD_DAYS:
                        reason = f"{MAX_HOLD_DAYS}일만기"
                    if reason is None:
                        if current_top is None:
                            current_top = {t for t, _ in rank_alts()}
                        if pos["coin"] not in current_top:
                            reason = "랭크아웃(Top3이탈)"

                    if reason:
                        mfe = favorable_pct
                        mae = (1 - pos["min_p"] / entry) * 100 * -1   # 불리방향(하락)이면 음수로 표시
                        pnl_usdt = NOTIONAL_USDT * (pnl / 100)
                        # ★ 2026-08-17(버그헌터 감사): del 직후 즉시 저장 — CSV기록보다 먼저
                        # positions.json을 반영해야, 저장 사이에 프로세스가 죽어도 최악의 경우
                        # "이 거래 기록이 조용히 누락"되는 데 그침(bc_rule_shadow_paper의 중복
                        # 재청산 버그처럼 같은 포지션이 두 번 로그되는 것보다 100건 표본 순수성에
                        # 덜 해로움).
                        del positions[sym]
                        _save(POS_PATH, positions)
                        _bm = pos.get("btc_mom_pct_at_entry")  # 2026-08-17 이전 진입한 포지션엔 없을 수 있음
                        log_trade(dict(entry_time=pos["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                                       symbol=sym, entry_price=entry, exit_price=px,
                                       mom_pct_at_entry=round(pos["mom_pct_at_entry"], 2),
                                       btc_mom_pct_at_entry=round(_bm, 2) if _bm is not None else "",
                                       notional_usdt=NOTIONAL_USDT, pnl_pct=round(pnl, 2),
                                       pnl_usdt=round(pnl_usdt, 2), reason=reason,
                                       mfe_pct=round(mfe, 2), mae_pct=round(mae, 2)))
                        log.warning(f"[모의청산] {sym} @{px:g} {reason} pnl={pnl:+.2f}%({pnl_usdt:+.2f}USDT)")

            # 2) 일일 1회 리랭크 + 신규진입(Top3인데 아직 미보유면 진입)
            if last_rerank_date != today:
                last_rerank_date = today
                top = rank_alts()
                for coin, mom in top:
                    sym = f"{coin}USDT"
                    if sym in positions:
                        continue
                    px = latest_price(coin)
                    if px <= 0:
                        continue
                    positions[sym] = {
                        "coin": coin,
                        "entry_price": px,
                        "entry_ts": now,
                        "entry_iso": datetime.now(KST).isoformat(),
                        "mom_pct_at_entry": mom,
                        "btc_mom_pct_at_entry": btc_mom_pct(),
                        "max_p": px, "min_p": px,
                    }
                    log.warning(f"[모의진입] {sym} @{px:g} 모멘텀{mom:+.1f}%(20일) Top{ALT_N}진입")
                _save(POS_PATH, positions)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    main()
