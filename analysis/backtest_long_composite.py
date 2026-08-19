"""[OFFLINE ANALYSIS TOOL] — 라이브/모의 트레이딩 봇 아님. watchdog 미등록. 네트워크 호출 없음.

alt_momentum_long 복합전략 후보(docs/_share_prompt18_long_composite_20260818.txt의 ②③) 역사적
백테스트. scripts/alt_momentum_long_paper.py(실제 상시가동 중인 순수모의 봇)는 이 스크립트가
"읽어서 상수를 그대로 베끼는" 참조 대상일 뿐, import도 안 하고 절대 수정하지 않음. 그 봇의
data/alt_momentum_long_pos.json · data/alt_momentum_long_trades.csv에도 일절 손대지 않음(둘 다
읽지도 않음 — 이 스크립트는 data/candles_daily/*.json만 읽는다). 출력은 전부 analysis/out/ 밑에
새로 씀.

배경: alt_momentum_long_paper는 2026-08-17 배포, 2026-08-18 현재 청산 2건뿐(포워드표본 부족).
반면 로컬 candles_daily엔 2024년 봄~현재까지 2년+ 일봉이 있어, "그 로직을 과거에 그대로
돌렸으면 어땠을지"를 훨씬 큰 표본으로 먼저 가늠해볼 수 있음 — 포워드 표본 축적(100건 목표)과는
별개의, 보완적 증거.

검증 대상 2가지(원 문서의 ②③, ①숏롱연동·④리랭크주기단축은 범위 밖 — 이미 각각 기각/보류됨):
  ② BTC 강세게이트(이분법: 200일선 위=100%, 아래=0%)를 "200일선 대비 괴리율에 비례하는
     연속 포지션사이징"으로 대체.
  ③ 진입랭킹에 "BTC대비 상대강도"(코인수익률-BTC수익률, 동일 룩백)를 2번째 팩터로 추가.
     ─ 중요: Manus(외부AI 자문)가 이미 대수적으로 증명한 대로, "상대강도로 재정렬"은 그
       비교시점의 모든 후보에서 BTC수익률이라는 동일 상수를 빼는 것이므로 순위가 절대모멘텀
       재정렬과 완전히 동일해짐(상수는 순서를 안 바꿈) — 이 스크립트 맨 아래
       verify_naive_relscore_is_noop()에서 로컬 데이터로 직접 재확인(며칠치가 아니라 전체
       기간). 그래서 ③은 "상대강도>0인 코인만 후보로 남기는 필터"로 구현함 — 필터는 순위를
       바꾸는 게 아니라 대상집합 자체를 바꾸므로 상쇄되지 않음(가이드 그대로 채택).

라이브 상수는 전부 scripts/alt_momentum_long_paper.py에서 그대로 복사(추측 금지, 값 바뀌면 이
파일도 다시 맞춰야 함 — 2026-08-18 시점 값):
  ALT_N=3, MOM_LB=20일, LIQ_FLOOR=1억원(20일평균거래대금), STALE_DAYS=2일,
  STOP_PCT=20%, TRAIL_TRIGGER=20%, TRAIL_GIVEBACK=10%, MAX_HOLD=21일, NOTIONAL_USDT=30.

데이터: data/candles_daily/{TICKER}_1d.json (업비트/빗썸형 일봉 포맷, trade_price=종가,
candle_acc_trade_price=당일 거래대금(원), candle_date_time_kst=일자). 청산판정은 그날의
"종가"만 사용(라이브가 실질적으로 latest_price()=최신 저장 종가를 쓰는 것과 동일선상 —
라이브는 6시간마다 폴링하며 update_daily_candles.py가 당일 진행중 캔들을 장중에도 계속
덮어쓰므로 사실상 "그 순간의 최근가 1개 값"을 쓰는 셈이라, 백테스트에서 "그날 종가 1개"로
근사하는 것이 데이터가 허용하는 한 가장 충실한 재현임 — 고가/저가 기반 장중 스침은 반영 안 함,
한계로 명시). 이 단순화는 baseline과 모든 variant에 동일하게 적용되므로 상호비교의 타당성은
유지됨.

Run: python analysis/backtest_long_composite.py
"""
import sys, json, glob, statistics as st
from pathlib import Path
from datetime import date, datetime
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "data" / "candles_daily"
OUT_DIR = ROOT / "analysis" / "out"

# ── scripts/alt_momentum_long_paper.py 와 100% 동일 상수(2026-08-18 시점 값 그대로 복사) ──
ALT_N = 3
MOM_LB = 20
LIQ_FLOOR = 100_000_000
STALE_DAYS = 2
STOP_PCT = 20.0
TRAIL_TRIGGER_PCT = 20.0
TRAIL_GIVEBACK_PCT = 10.0
MAX_HOLD_DAYS = 21
NOTIONAL_USDT = 30.0

# ── hybrid_trader.py/core_trader.py의 기존 이분법 게이트와 동일 정의(② 비교기준) ──
SMA_SLOW = 200

# ── ② 전용 신규 정의(라이브에 없음 — 이 백테스트만의 실험적 공식, 결과 해석 시 감안) ──
# dist_pct = BTC 종가의 200일선 대비 괴리율(%). multiplier = clip(1 + dist_pct/SCALE, FLOOR, CAP).
# dist_pct=0(200일선상)일 때 배율 1.0(=현행 고정 30USDT와 동일) — 기존 이분법 게이트의 전환점
# (약 +1%)과 거의 일치하도록 기준점을 맞춤. SCALE=50이므로 괴리 ±50%p당 배율 ±1.0.
# 바닥(0.3배=9U)·천장(2.0배=60U)을 둔 이유: 이 봇 자체가 "BTC 약세에도 알트 개별모멘텀은
# 유효할 수 있다"는 전제로 이분법 게이트를 없앤 것이므로, BTC가 아무리 약해도 완전 배제(0배)는
# 하지 않고 축소된 크기로는 계속 참여시킴. 반대로 무한 레버리지도 막음.
SIZE_FLOOR_MULT = 0.3
SIZE_CAP_MULT = 2.0
SIZE_SCALE_PCT = 50.0


# ══════════════════════════════ 데이터 로딩 ══════════════════════════════

class Series:
    __slots__ = ("ticker", "dates", "closes", "vols")
    def __init__(self, ticker, dates, closes, vols):
        self.ticker = ticker
        self.dates = dates      # date, 오름차순
        self.closes = closes
        self.vols = vols        # candle_acc_trade_price(원)


def load_series(path: Path) -> Series | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not d:
        return None
    d.sort(key=lambda c: c.get("candle_date_time_kst", ""))
    dates, closes, vols = [], [], []
    for c in d:
        try:
            dt = datetime.fromisoformat(c["candle_date_time_kst"]).date()
            dates.append(dt)
            closes.append(float(c["trade_price"]))
            vols.append(float(c.get("candle_acc_trade_price", 0)))
        except Exception:
            continue
    if not dates:
        return None
    ticker = path.stem.replace("_1d", "")
    return Series(ticker, dates, closes, vols)


def load_universe():
    files = sorted(DAILY_DIR.glob("*_1d.json"))
    series = {}
    for f in files:
        s = load_series(f)
        if s:
            series[s.ticker] = s
    return series


# ══════════════════════════ 날짜→인덱스 사전계산(전 variant 공용) ══════════════════════════

def precompute_idx_by_calendar(series: dict[str, Series], calendar: list[date]):
    """ticker -> calendar와 같은 길이의 배열. arr[i] = '해당 티커 자체 배열에서 calendar[i]
    이하인 가장 최근 캔들의 인덱스'(없으면 -1). 라이브의 cl[-1](=그 시점 최신 종가)을
    과거 임의 시점 d로 일반화한 것 — 포인터 전진 방식이라 티커당 O(len(dates))."""
    out = {}
    for t, s in series.items():
        arr = [-1] * len(calendar)
        j = -1
        k = 0
        n = len(s.dates)
        for i, d in enumerate(calendar):
            while k < n and s.dates[k] <= d:
                j = k
                k += 1
            arr[i] = j
        out[t] = arr
    return out


# ══════════════════════════════ 랭킹 로직 ══════════════════════════════

def rank_at(i, calendar, series, idx_by_cal, btc_mom_by_day, rel_filter: bool):
    """rank_alts()의 백테스트 재현(라이브 scripts/alt_momentum_long_paper.py의 rank_alts()와
    동일 필터 순서: staleness → 모멘텀 최소길이 → 유동성플로어 → (rel_filter시) 상대강도>0.
    반환: [(mom_pct, ticker), ...] 모멘텀 내림차순 top ALT_N개."""
    d = calendar[i]
    bm = btc_mom_by_day[i] if rel_filter else None
    if rel_filter and bm is None:
        return []  # BTC 20일 모멘텀 계산 불가(극초반) → 상대강도 판정 불가, 보수적으로 후보 0
    scored = []
    for t, s in series.items():
        if t == "BTC":
            continue
        idx = idx_by_cal[t][i]
        if idx < 0 or idx < MOM_LB:
            continue
        # staleness: 해당 시점 d 기준으로 그 티커의 '가장 최근 캔들'이 STALE_DAYS 넘게 뒤처졌는가
        # (라이브의 datetime.now(KST)-last 를 일 단위로 단순화 — 백테스트 자체가 일봉 그리드라 적절)
        if (d - s.dates[idx]).days > STALE_DAYS:
            continue
        past = s.closes[idx - MOM_LB]
        if past <= 0:
            continue
        mom = (s.closes[idx] / past - 1) * 100
        vols = s.vols[idx - MOM_LB + 1: idx + 1]
        if not vols or sum(vols) / len(vols) < LIQ_FLOOR:
            continue
        if rel_filter and (mom - bm) <= 0:
            continue
        scored.append((mom, t))
    scored.sort(reverse=True)
    return scored[:ALT_N]


def rank_at_naive_relscore(i, calendar, series, idx_by_cal, btc_mom_by_day):
    """③의 '순진한' 버전 — 필터가 아니라 (모멘텀-BTC모멘텀)으로 재정렬. 이론상 baseline과
    top집합이 완전히 같아야 함(상수 차감은 순서를 보존) — verify_naive_relscore_is_noop()에서
    실제로 그런지 전기간 검증. 본선 4개 variant엔 쓰지 않음(안내문 요구사항: 무의미함을
    확인만 하고, 실제 사용은 필터형으로)."""
    d = calendar[i]
    bm = btc_mom_by_day[i]
    if bm is None:
        return []
    scored = []
    for t, s in series.items():
        if t == "BTC":
            continue
        idx = idx_by_cal[t][i]
        if idx < 0 or idx < MOM_LB:
            continue
        if (d - s.dates[idx]).days > STALE_DAYS:
            continue
        past = s.closes[idx - MOM_LB]
        if past <= 0:
            continue
        mom = (s.closes[idx] / past - 1) * 100
        vols = s.vols[idx - MOM_LB + 1: idx + 1]
        if not vols or sum(vols) / len(vols) < LIQ_FLOOR:
            continue
        scored.append((mom - bm, t))   # ← 유일한 차이: 정렬키가 상대점수
    scored.sort(reverse=True)
    return scored[:ALT_N]


# ══════════════════════════════ 시뮬레이션 ══════════════════════════════

def simulate(calendar, series, idx_by_cal, top_by_day, size_mode: str,
             btc_close_by_day, btc_sma200_by_day):
    """top_by_day[i] = 그날의 [(mom,ticker),...] (사전계산된 랭킹, baseline/②는 rel_filter=False용,
    ③/②+③은 rel_filter=True용을 그대로 재사용 — 동일 날짜엔 항상 동일 결과이므로 재사용해도
    라이브의 '같은 사이클에 rank_alts() 두 번 호출'과 결과상 동일, 계산만 절약).
    size_mode: "fixed"(고정 NOTIONAL_USDT) | "continuous"(② 연속사이징).
    라이브와 동일한 처리순서: 1) 보유 포지션 청산판정(스탑>트레일>만기>랭크아웃) 2) 신규진입
    (당일 top인데 미보유면 진입) — 같은 사이클 내 재진입 허용 quirk까지 그대로 재현
    (라이브 코드 흐름 그대로: exit에서 del된 직후의 positions dict를 entry 단계가 그대로 봄)."""
    positions = {}
    trades = []
    equity_curve = []
    realized = 0.0

    for i, d in enumerate(calendar):
        top = top_by_day[i]
        top_set = {t for _, t in top}

        # 1) 청산판정
        for sym in list(positions.keys()):
            pos = positions[sym]
            idx = idx_by_cal[pos["coin"]][i]
            if idx < 0:
                continue
            px = series[pos["coin"]].closes[idx]
            if px <= 0:
                continue
            pos["max_p"] = max(pos["max_p"], px)
            pos["min_p"] = min(pos["min_p"], px)
            entry = pos["entry_price"]
            favorable_pct = (pos["max_p"] / entry - 1) * 100
            pnl = (px / entry - 1) * 100
            hold_days = (d - pos["entry_date"]).days

            reason = None
            if px <= entry * (1 - STOP_PCT / 100):
                reason = f"스탑-{STOP_PCT:.0f}%"
            elif favorable_pct >= TRAIL_TRIGGER_PCT:
                trail_level = pos["max_p"] * (1 - TRAIL_GIVEBACK_PCT / 100)
                if px <= trail_level:
                    reason = f"트레일(최고{favorable_pct:.0f}%->{pnl:.0f}%)"
            if reason is None and hold_days >= MAX_HOLD_DAYS:
                reason = f"{MAX_HOLD_DAYS}일만기"
            if reason is None and pos["coin"] not in top_set:
                reason = "랭크아웃(Top3이탈)"

            if reason:
                pnl_usdt = pos["notional"] * (pnl / 100)
                realized += pnl_usdt
                mae = (1 - pos["min_p"] / entry) * 100 * -1
                trades.append(dict(
                    entry_date=pos["entry_date"].isoformat(), exit_date=d.isoformat(),
                    symbol=sym, coin=pos["coin"], entry_price=entry, exit_price=px,
                    mom_pct_at_entry=round(pos["mom_at_entry"], 2),
                    notional_usdt=round(pos["notional"], 4),
                    pnl_pct=round(pnl, 4), pnl_usdt=round(pnl_usdt, 4), reason=reason,
                    hold_days=hold_days, mfe_pct=round(favorable_pct, 2), mae_pct=round(mae, 2),
                ))
                del positions[sym]

        # 2) 신규진입(당일 Top인데 미보유)
        for mom, coin in top:
            sym = f"{coin}USDT"
            if sym in positions:
                continue
            idx = idx_by_cal[coin][i]
            if idx < 0:
                continue
            px = series[coin].closes[idx]
            if px <= 0:
                continue
            notional = NOTIONAL_USDT
            if size_mode == "continuous":
                bc, bs = btc_close_by_day[i], btc_sma200_by_day[i]
                if bc and bs:
                    dist_pct = (bc / bs - 1) * 100
                    mult = min(max(1 + dist_pct / SIZE_SCALE_PCT, SIZE_FLOOR_MULT), SIZE_CAP_MULT)
                else:
                    mult = 1.0   # BTC 200일선 미형성 구간(극초반) 폴백 — 판단근거 없으니 중립 100%
                notional = NOTIONAL_USDT * mult
            positions[sym] = dict(coin=coin, entry_price=px, entry_date=d,
                                   mom_at_entry=mom, notional=notional, max_p=px, min_p=px)

        # 일별 마크투마켓 자산(realized + 미청산 평가손익) — 드로다운 계산용
        unrl = 0.0
        for pos in positions.values():
            idx = idx_by_cal[pos["coin"]][i]
            if idx >= 0:
                px = series[pos["coin"]].closes[idx]
                unrl += pos["notional"] * (px / pos["entry_price"] - 1)
        equity_curve.append((d, realized + unrl))

    return trades, equity_curve


# ══════════════════════════════ 통계 요약 ══════════════════════════════

def max_drawdown(equity_curve):
    if not equity_curve:
        return 0.0, None, None
    peak = equity_curve[0][1]
    peak_date = equity_curve[0][0]
    worst_dd, worst_peak_d, worst_trough_d = 0.0, peak_date, peak_date
    for d, eq in equity_curve:
        if eq > peak:
            peak = eq
            peak_date = d
        dd = eq - peak
        if dd < worst_dd:
            worst_dd, worst_peak_d, worst_trough_d = dd, peak_date, d
    return worst_dd, worst_peak_d, worst_trough_d


def summarize(trades, equity_curve, label):
    n = len(trades)
    if n == 0:
        return dict(label=label, n=0)
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(wins) / n * 100
    avg_win = st.mean(t["pnl_pct"] for t in wins) if wins else 0.0
    avg_loss = st.mean(t["pnl_pct"] for t in losses) if losses else 0.0
    avg_pnl_pct = st.mean(t["pnl_pct"] for t in trades)
    total_pnl_usdt = sum(t["pnl_usdt"] for t in trades)
    total_notional = sum(t["notional_usdt"] for t in trades)
    dollar_wtd_return_pct = (total_pnl_usdt / total_notional * 100) if total_notional else 0.0
    gross_win = sum(t["pnl_usdt"] for t in wins)
    gross_loss = -sum(t["pnl_usdt"] for t in losses)
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = float("inf") if gross_win > 0 else 0.0
    dd, peak_d, trough_d = max_drawdown(equity_curve)
    return dict(label=label, n=n, win_rate=win_rate, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
                avg_pnl_pct=avg_pnl_pct, total_pnl_usdt=total_pnl_usdt, total_notional=total_notional,
                dollar_wtd_return_pct=dollar_wtd_return_pct, profit_factor=pf,
                max_dd_usdt=dd, max_dd_peak=str(peak_d), max_dd_trough=str(trough_d),
                avg_notional=total_notional / n)


def fmt_pf(pf):
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def print_table(rows):
    hdr = f"{'variant':<16}{'N':>5}{'승률%':>8}{'평균%':>8}{'평균익%':>9}{'평균손%':>9}{'PF':>7}{'총손익U':>11}{'투입U':>9}{'달러가중%':>10}{'MDD(U)':>9}{'평균notional':>13}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if r["n"] == 0:
            print(f"{r['label']:<16}{'0':>5}  (거래 없음)")
            continue
        print(f"{r['label']:<16}{r['n']:>5}{r['win_rate']:>7.1f}%{r['avg_pnl_pct']:>7.2f}%"
              f"{r['avg_win_pct']:>8.2f}%{r['avg_loss_pct']:>8.2f}%{fmt_pf(r['profit_factor']):>7}"
              f"{r['total_pnl_usdt']:>11.2f}{r['total_notional']:>9.1f}"
              f"{r['dollar_wtd_return_pct']:>9.2f}%{r['max_dd_usdt']:>9.2f}{r['avg_notional']:>13.2f}")


def save_trades_csv(trades, path):
    import csv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["entry_date", "exit_date", "symbol", "coin", "entry_price", "exit_price",
              "mom_pct_at_entry", "notional_usdt", "pnl_pct", "pnl_usdt", "reason",
              "hold_days", "mfe_pct", "mae_pct"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow(t)


# ══════════════════════════════ 메인 ══════════════════════════════

def main():
    print("=" * 78)
    print("[OFFLINE ANALYSIS] alt_momentum_long 복합전략(②BTC연속사이징 / ③상대강도필터) 백테스트")
    print("라이브/모의봇 아님. watchdog 미등록. data/candles_daily/*.json 로컬데이터만 사용(네트워크X)")
    print("=" * 78)

    series = load_universe()
    if "BTC" not in series:
        print("[FATAL] data/candles_daily/BTC_1d.json 없음 — BTC 200일선/모멘텀 계산 불가, 중단")
        return
    btc = series["BTC"]
    calendar = btc.dates[:]  # BTC는 무결측 확인됨(813일 연속) → 전체 시뮬레이션 캘린더로 채택
    n_days = len(calendar)
    n_tickers = len(series)
    print(f"\n데이터 커버리지: 티커 {n_tickers}개(BTC 제외 알트 {n_tickers-1}개), "
          f"캘린더 {calendar[0]}~{calendar[-1]} ({n_days}일)")

    if n_days < 180:
        print("[경고] 로컬 캔들 히스토리가 6개월 미만 — 표본 자체가 결론을 내리기엔 너무 짧음.")

    idx_by_cal = precompute_idx_by_calendar(series, calendar)

    # BTC 파생 시계열(모든 variant 공용, 1회만 계산)
    btc_idx_by_day = idx_by_cal["BTC"]
    btc_close_by_day = [btc.closes[j] if j >= 0 else None for j in btc_idx_by_day]
    btc_mom_by_day = []
    for j in btc_idx_by_day:
        if j is None or j < MOM_LB or j < 0:
            btc_mom_by_day.append(None)
        else:
            past = btc.closes[j - MOM_LB]
            btc_mom_by_day.append((btc.closes[j] / past - 1) * 100 if past > 0 else None)
    btc_sma200_by_day = []
    for j in btc_idx_by_day:
        if j is None or j < SMA_SLOW - 1 or j < 0:
            btc_sma200_by_day.append(None)
        else:
            window = btc.closes[j - SMA_SLOW + 1: j + 1]
            btc_sma200_by_day.append(sum(window) / len(window))

    sma_start_i = next((i for i, v in enumerate(btc_sma200_by_day) if v is not None), None)
    print(f"BTC 200일선 형성 시작일: {calendar[sma_start_i] if sma_start_i is not None else 'N/A'} "
          f"(그 이전 {sma_start_i}일은 ②의 사이징이 중립 1.0배로 폴백)")

    # 랭킹 사전계산(전 variant 공용 — baseline/②는 rel_filter=False, ③/②+③은 True)
    print("\n랭킹 사전계산 중...")
    top_raw = [rank_at(i, calendar, series, idx_by_cal, btc_mom_by_day, rel_filter=False)
               for i in range(n_days)]
    top_relfilter = [rank_at(i, calendar, series, idx_by_cal, btc_mom_by_day, rel_filter=True)
                      for i in range(n_days)]

    # ── ③ 순진한(naive) 재정렬 버전이 실제로 no-op인지 전기간 실증 ──
    verify_naive_relscore_is_noop(calendar, series, idx_by_cal, btc_mom_by_day, top_raw)

    # ── ③ 필터가 실제로 얼마나 자주 baseline과 다른 Top3을 고르는지 진단 ──
    days_with_bm = sum(1 for bm in btc_mom_by_day if bm is not None)
    differs = sum(1 for i in range(n_days)
                  if btc_mom_by_day[i] is not None and
                  {t for _, t in top_raw[i]} != {t for _, t in top_relfilter[i]})
    print(f"\n[③ 필터 진단] BTC모멘텀 계산가능 {days_with_bm}일 중 baseline Top3과 "
          f"'상대강도>0 필터' Top3이 달라지는 날: {differs}일 "
          f"({differs/days_with_bm*100 if days_with_bm else 0:.1f}%)")

    # ── 4개 variant 시뮬레이션 ──
    print("\n시뮬레이션 실행 중...")
    trades_base, eq_base = simulate(calendar, series, idx_by_cal, top_raw, "fixed",
                                     btc_close_by_day, btc_sma200_by_day)
    trades_rel, eq_rel = simulate(calendar, series, idx_by_cal, top_relfilter, "fixed",
                                   btc_close_by_day, btc_sma200_by_day)
    trades_size, eq_size = simulate(calendar, series, idx_by_cal, top_raw, "continuous",
                                     btc_close_by_day, btc_sma200_by_day)
    trades_combo, eq_combo = simulate(calendar, series, idx_by_cal, top_relfilter, "continuous",
                                       btc_close_by_day, btc_sma200_by_day)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    save_trades_csv(trades_base, OUT_DIR / "trades_baseline.csv")
    save_trades_csv(trades_rel, OUT_DIR / "trades_relfilter_idea3.csv")
    save_trades_csv(trades_size, OUT_DIR / "trades_contsize_idea2.csv")
    save_trades_csv(trades_combo, OUT_DIR / "trades_combined_idea2and3.csv")

    print(f"\n{'='*78}\n[전체기간] {calendar[0]} ~ {calendar[-1]} ({n_days}일) — 전체 트레이드\n{'='*78}")
    rows_full = [
        summarize(trades_base, eq_base, "baseline(현행)"),
        summarize(trades_rel, eq_rel, "③상대강도필터"),
        summarize(trades_size, eq_size, "②연속사이징"),
        summarize(trades_combo, eq_combo, "②+③결합"),
    ]
    print_table(rows_full)

    # ── 공통비교구간(BTC 200일선 형성 이후) — ②가 실제로 작동하는 구간만 떼서 4개를 동일 조건 비교 ──
    if sma_start_i is not None:
        cutoff = calendar[sma_start_i]
        def restrict(trades, eq):
            t2 = [t for t in trades if date.fromisoformat(t["entry_date"]) >= cutoff]
            e2 = [e for e in eq if e[0] >= cutoff]
            return t2, e2
        rb, eb = restrict(trades_base, eq_base)
        rr, er = restrict(trades_rel, eq_rel)
        rs, es = restrict(trades_size, eq_size)
        rc, ec = restrict(trades_combo, eq_combo)
        print(f"\n{'='*78}\n[공통비교구간] {cutoff} ~ {calendar[-1]} "
              f"(BTC 200일선 형성 이후 — ②가 폴백 없이 실제로 작동하는 구간, 4개 동일조건)\n{'='*78}")
        rows_common = [
            summarize(rb, eb, "baseline(현행)"),
            summarize(rr, er, "③상대강도필터"),
            summarize(rs, es, "②연속사이징"),
            summarize(rc, ec, "②+③결합"),
        ]
        print_table(rows_common)
    else:
        rows_common = []

    # ── 요약 JSON 저장 ──
    summary = dict(
        generated_at=datetime.now().isoformat(),
        data_coverage=dict(n_tickers=n_tickers, calendar_start=str(calendar[0]),
                            calendar_end=str(calendar[-1]), n_days=n_days,
                            btc_sma200_start=str(calendar[sma_start_i]) if sma_start_i is not None else None),
        full_period=rows_full,
        common_window=rows_common,
        idea3_filter_diagnostic=dict(days_with_btc_mom=days_with_bm, days_differ_from_baseline=differs),
        constants=dict(ALT_N=ALT_N, MOM_LB=MOM_LB, LIQ_FLOOR=LIQ_FLOOR, STALE_DAYS=STALE_DAYS,
                        STOP_PCT=STOP_PCT, TRAIL_TRIGGER_PCT=TRAIL_TRIGGER_PCT,
                        TRAIL_GIVEBACK_PCT=TRAIL_GIVEBACK_PCT, MAX_HOLD_DAYS=MAX_HOLD_DAYS,
                        NOTIONAL_USDT=NOTIONAL_USDT, SMA_SLOW=SMA_SLOW,
                        SIZE_FLOOR_MULT=SIZE_FLOOR_MULT, SIZE_CAP_MULT=SIZE_CAP_MULT,
                        SIZE_SCALE_PCT=SIZE_SCALE_PCT),
    )
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                           encoding="utf-8")
    print(f"\n결과 저장: {OUT_DIR}\\summary.json, trades_*.csv (4개)")


def verify_naive_relscore_is_noop(calendar, series, idx_by_cal, btc_mom_by_day, top_raw):
    """가이드 요구사항: '상대강도로 그냥 재정렬'이 baseline과 동일 결과임을 실제 데이터로
    실증(대수적 증명의 경험적 재확인). 순진한 재정렬 Top3 집합/순서를 baseline과 전기간 비교."""
    n_days = len(calendar)
    set_match = 0
    order_match = 0
    checked = 0
    for i in range(n_days):
        if btc_mom_by_day[i] is None:
            continue
        naive = rank_at_naive_relscore(i, calendar, series, idx_by_cal, btc_mom_by_day)
        checked += 1
        raw_set = {t for _, t in top_raw[i]}
        naive_set = {t for _, t in naive}
        if raw_set == naive_set:
            set_match += 1
        raw_order = [t for _, t in top_raw[i]]
        naive_order = [t for _, t in naive]
        if raw_order == naive_order:
            order_match += 1
    pct_set = set_match / checked * 100 if checked else 0.0
    pct_order = order_match / checked * 100 if checked else 0.0
    print(f"\n[③ 순진한 재정렬 = no-op 검증] BTC모멘텀 계산가능 {checked}일 전체 대상:")
    print(f"  Top3 '집합' 일치율: {pct_set:.2f}% ({set_match}/{checked})")
    print(f"  Top3 '순서(내림차순 전체)' 일치율: {pct_order:.2f}% ({order_match}/{checked})")
    if pct_set >= 99.9:
        print("  → Manus의 대수적 증명대로, '상대강도로 재정렬'은 baseline(절대모멘텀 정렬)과")
        print("    사실상 동일한 결과. 이 백테스트는 이 버전을 본선 4개 variant에 포함하지 않고,")
        print("    '상대강도>0 필터'(대상집합 자체를 바꿈)만 ③의 실제 구현으로 채택함.")
    else:
        print(f"  → 완전 100%가 아님(부동소수점 근접동률 등 미세 노이즈 가능성) — set_match가 "
              f"99.9% 미만이면 코드를 재검토할 것.")


if __name__ == "__main__":
    main()
