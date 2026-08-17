"""
b/c룰 모의 병렬검증기 (bc_rule_shadow_paper) — 순수 모의, 매매 API 미호출.

목적(2026-08-16, MiniMax 재자문 제안 채택): 51건 동결이 끝난 뒤에야 손실축소 룰(b·c)을
검증하면, 그 룰 자체를 검증하려고 또 새로운 동결기간(수십 건)을 잡아야 함 — "51건 다음
30~50건"이 또 필요해져 시간이 배로 걸림. 대신 지금부터 실전 진입을 그대로 미러링하되
청산 규칙만 후보안(b·c룰)으로 바꿔서 모의로 병렬 운영하면, 51건 완료 시점에 이미
"이 룰을 썼으면 어땠을지" 비교 데이터가 쌓여있음. 실전(margin_short_trader.py)에는
전혀 영향 없음 — 같은 신호를 그냥 옆에서 다른 규칙으로 한 번 더 관찰하는 것.

적용 규칙(docs/would_change_log.md 2026-08-13 MiniMax/Perplexity/ChatGPT/Gemini
4개AI 교차검증 합의안, c=추세반전조기청산 1순위 + b=시간기반조기손절 보조):
  - MAE(불리방향 이동) -12% 도달 시: 포지션 절반 청산 + 남은 절반 손절폭 -25%로 타이트닝
  - MAE -20% 도달 시: 잔여 전량 즉시 청산
  - 유리방향(가격하락) +15% 도달 시: 실전과 동일 트레일링 무장(10%p 반납 시 청산)
    — 이 부분은 실전과 동일하게 둬서 "새 c룰이 추가로 뭘 바꾸는지"만 순수 비교 가능하게 함
  - b룰(시간기반): 진입 후 HOLD_H/2(24h) 경과 시점에 아직 불리(pnl<=0)면 조기 청산
  - 위 어느 것도 안 걸리면 실전과 동일 48h 만기

동작: data/margin_short_pos.json을 폴링해 실전에 새로 뜬 포지션을 그대로 미러링(같은
심볼·진입가·진입시각·증거금) → 이후 독립적으로 위 규칙으로 관리 → 모의 청산 시
data/bc_rule_shadow_trades.csv에 기록. 실전 포지션이 우리보다 먼저 청산돼도(다른 규칙이라
청산시점 다름) 상관없이 계속 추적 — 완전히 별개 타임라인.

★ 순수 모의: 매매 API 미호출. 포트 47255.
상태 data/bc_rule_shadow_pos.json | 기록 data/bc_rule_shadow_trades.csv | 로그 logs/bc_rule_shadow_paper.log
Run: python scripts/bc_rule_shadow_paper.py
"""
import sys, atexit, time, json, csv, socket, logging
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
    try: _sock.bind(("127.0.0.1", 47255))
    except OSError: print("[ERROR] bc_rule_shadow_paper 이미 실행 중 (포트 47255)."); sys.exit(1)
    atexit.register(_sock.close)
_single()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [BCSHADOW] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/bc_rule_shadow_paper.log", encoding="utf-8")])
log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"
POLL_SEC = 60
REAL_POS_PATH = ROOT / "data" / "margin_short_pos.json"
SHADOW_POS_PATH = ROOT / "data" / "bc_rule_shadow_pos.json"
SHADOW_TRADES_PATH = ROOT / "data" / "bc_rule_shadow_trades.csv"
# ★ 2026-08-17(버그 발견): 실전 포지션은 열려있는데 그림자가 c룰로 먼저 청산하면(realtime
# 다른 규칙이라 청산시점이 다름), shadow에서 del된 뒤 다음 루프에서 REAL_POS_PATH에 여전히
# 있는 걸 "새 진입"으로 재미러링해서 매 사이클(1분) 무한 재진입→재청산 반복(PORTAL 119회
# 중복 발생). 심볼+진입시각 조합을 영구 기록해 같은 실전 진입을 두 번 미러링하지 않게 함.
PROCESSED_PATH = ROOT / "data" / "bc_rule_shadow_processed.json"

# 실전과 동일(비교의 기준선을 맞추기 위해 그대로 사용)
HOLD_H = 48.0
TRAIL_TRIGGER_PCT = 15.0
TRAIL_GIVEBACK_PCT = 10.0
STOP_PCT_ORIG = 40.0
# c룰(신규): 단계적 손절 타이트닝
MAE_HALF_CLOSE_PCT = 12.0
MAE_HALF_CLOSE_NEW_STOP_PCT = 25.0
MAE_FULL_CLOSE_PCT = 20.0
# b룰(신규): 시간기반 조기손절
TIME_CHECK_H = HOLD_H / 2   # 24h
TIME_CHECK_REQUIRE_FAVORABLE = 0.0   # 이 시점 pnl<=0(전혀 유리한 적 없음)이면 조기청산


def _load(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d
def _save(p, o):
    tmp = Path(p).with_suffix(".tmp"); tmp.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(p)


def price(sym):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/price", params={"symbol": sym}, timeout=8)
        return float(r.json()["price"]) if r.status_code == 200 else 0.0
    except Exception:
        return 0.0


def log_trade(row):
    new = not SHADOW_TRADES_PATH.exists()
    with open(SHADOW_TRADES_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["entry_time", "exit_time", "symbol", "entry_price", "exit_price",
                                           "margin_usdt", "pnl_pct", "pnl_usdt", "reason", "mirrors_real"])
        if new: w.writeheader()
        w.writerow(row)


def mirror_new_positions(shadow, processed):
    real = _load(REAL_POS_PATH, {})
    for sym, rp in real.items():
        key = f"{sym}:{rp['entry_ts']}"
        if sym in shadow or key in processed:
            continue
        shadow[sym] = {
            "coin": rp.get("coin", sym.replace("USDT", "")),
            "entry_price": rp["entry_price"],
            "entry_ts": rp["entry_ts"],
            "entry_iso": rp.get("entry_iso", datetime.now(KST).isoformat()),
            "margin_full": rp["margin"],
            "margin_remaining": rp["margin"],
            "half_closed": False,
            "stop_pct_current": STOP_PCT_ORIG,
            "min_p": rp["entry_price"], "max_p": rp["entry_price"],
            "armed": False,
            "time_check_done": False,
            "realized_pnl_usdt": 0.0,
        }
        log.info(f"[미러진입] {sym} @{rp['entry_price']:g} 증거금{rp['margin']:.0f} (실전 신호 그대로 복사)")
    return shadow


def main():
    shadow = _load(SHADOW_POS_PATH, {})
    processed = _load(PROCESSED_PATH, {})
    log.info(f"b/c룰 모의 병렬검증 시작 — 실전 진입 미러링, MAE-{MAE_HALF_CLOSE_PCT:.0f}%반절+스탑-{MAE_HALF_CLOSE_NEW_STOP_PCT:.0f}%타이트닝 / "
             f"MAE-{MAE_FULL_CLOSE_PCT:.0f}%전량청산 / {TIME_CHECK_H:.0f}h시점 불리시 조기청산 / 순수모의(매매0)")
    try:
        from bithumb import notify
        notify.send("🧪 b/c룰 모의 병렬검증 시작 — 순수모의(매매0), 51건 실전과 동일신호 다른청산규칙 비교")
    except Exception: pass

    while True:
        try:
            shadow = mirror_new_positions(shadow, processed)
            now = time.time()

            for sym in list(shadow.keys()):
                p = shadow[sym]
                px = price(sym)
                if px <= 0:
                    continue
                p["min_p"] = min(p["min_p"], px)
                p["max_p"] = max(p["max_p"], px)
                entry = p["entry_price"]
                mae_pct = (px / entry - 1) * 100          # 숏 기준 불리방향(가격상승)
                favorable_pct = (1 - p["min_p"] / entry) * 100
                pnl_pct = (1 - px / entry) * 100
                hold_h = (now - p["entry_ts"]) / 3600

                exit_reason = None
                partial = False

                # c룰: 단계적 타이트닝
                if not p["half_closed"] and mae_pct >= MAE_HALF_CLOSE_PCT:
                    half_margin = p["margin_remaining"] / 2
                    half_pnl_usdt = half_margin * 2 * (-mae_pct / 100)
                    p["realized_pnl_usdt"] += half_pnl_usdt
                    p["margin_remaining"] -= half_margin
                    p["half_closed"] = True
                    p["stop_pct_current"] = MAE_HALF_CLOSE_NEW_STOP_PCT
                    log.warning(f"[c룰-절반청산] {sym} MAE{mae_pct:+.1f}% 절반청산({half_pnl_usdt:+.2f}USDT) "
                                f"잔여증거금{p['margin_remaining']:.1f} 스탑타이트닝→-{MAE_HALF_CLOSE_NEW_STOP_PCT:.0f}%")

                if mae_pct >= MAE_FULL_CLOSE_PCT:
                    exit_reason = f"c룰-MAE{MAE_FULL_CLOSE_PCT:.0f}%전량청산"
                elif p["stop_pct_current"] < STOP_PCT_ORIG and mae_pct >= p["stop_pct_current"]:
                    exit_reason = f"c룰-타이트닝스탑-{p['stop_pct_current']:.0f}%"
                elif px >= entry * (1 + STOP_PCT_ORIG / 100):
                    exit_reason = f"원스탑-{STOP_PCT_ORIG:.0f}%"

                # 실전과 동일 트레일링
                if exit_reason is None:
                    if not p["armed"] and favorable_pct >= TRAIL_TRIGGER_PCT:
                        p["armed"] = True
                    if p["armed"]:
                        trail_level = p["min_p"] * (1 + TRAIL_GIVEBACK_PCT / 100)
                        if px >= trail_level:
                            exit_reason = f"트레일링(최고{favorable_pct:.0f}%→{pnl_pct:.0f}%)"

                # b룰: 시간기반 조기손절
                if exit_reason is None and not p["time_check_done"] and hold_h >= TIME_CHECK_H:
                    p["time_check_done"] = True
                    if pnl_pct <= TIME_CHECK_REQUIRE_FAVORABLE:
                        exit_reason = f"b룰-{TIME_CHECK_H:.0f}h시점불리조기청산(pnl{pnl_pct:+.1f}%)"

                if exit_reason is None and hold_h >= HOLD_H:
                    exit_reason = f"{HOLD_H:.0f}h만기"

                if exit_reason:
                    final_pnl_usdt = p["margin_remaining"] * 2 * (pnl_pct / 100)
                    total_pnl_usdt = p["realized_pnl_usdt"] + final_pnl_usdt
                    total_pnl_pct = (total_pnl_usdt / (p["margin_full"] * 2)) * 100
                    log_trade(dict(entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(), symbol=sym,
                                   entry_price=entry, exit_price=px, margin_usdt=p["margin_full"],
                                   pnl_pct=round(total_pnl_pct, 2), pnl_usdt=round(total_pnl_usdt, 2),
                                   reason=exit_reason, mirrors_real=True))
                    log.warning(f"[모의청산] {sym} @{px:g} {exit_reason} 총pnl={total_pnl_pct:+.2f}%({total_pnl_usdt:+.2f}USDT)")
                    processed[f"{sym}:{p['entry_ts']}"] = True
                    del shadow[sym]

            # ★ 2026-08-17(버그헌터 발견): processed를 먼저 저장해야 함. 순서가 반대(shadow
            #   먼저)면, 그 사이(shadow저장 성공~processed저장 전)에 프로세스가 죽었을 때
            #   재시작 후 "shadow엔 없는데 processed에도 없는" 상태가 돼서 Case#1과 똑같이
            #   무한 재미러링이 재발함. processed를 먼저 저장하면 최악의 경우도 "중복 로그
            #   한 줄"에서 그침(무한루프로 안 번짐) — 원칙4(실패모드 카탈로그) 적용.
            _save(PROCESSED_PATH, processed)
            _save(SHADOW_POS_PATH, shadow)
        except Exception as e:
            log.error(f"루프오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
