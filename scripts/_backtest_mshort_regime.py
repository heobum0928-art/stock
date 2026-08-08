"""[분석] 마진숏 전략 — BTC 변동성(시장 레짐)별 성과 비교.
2026-08-07: 학술연구(팬데믹 시기 반전효과 역전 사례)를 근거로, "비트코인 자체가
크게 흔들리는 시기"에 우리 급등되돌림 숏 전략 성과가 달라지는지 검증.
방법: 각 진입신호 시점 기준 최근 24h(288×5분봉) 비트코인 변동폭(고가-저가)/시가%로
"시장 변동성"을 측정, 상/하위로 나눠 승률·평균수익 비교.
"""
import sys, json, glob, statistics as st
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
USE_EXT = len(sys.argv) > 1 and sys.argv[1] == "ext"
KDIR = ROOT / "data" / "binance_klines_ext" if USE_EXT else ROOT / "data" / "binance_klines"
if USE_EXT and not any(KDIR.glob("*_5m.json")):
    KDIR = ROOT / "data" / "binance_klines"

LOOKBACK = 84
PUMP_PCT = 30.0
HOLD = 576
COOLDOWN_BARS = 144
COST = 0.10
STOP_PCT = 40.0
BTC_VOL_WINDOW = 288  # 24h


def load_ohlc(f):
    d = json.load(open(f, encoding="utf-8"))
    return ([float(x[4]) for x in d], [float(x[2]) for x in d],
            [float(x[3]) for x in d], [float(x[1]) for x in d])  # close, high, low, open


def btc_vol_series(btc_high, btc_low, btc_open, n):
    """각 바 인덱스 기준 직전 24h(288봉) 변동폭% — 미리 계산해 룩업 배열로."""
    vol = [0.0] * n
    for i in range(BTC_VOL_WINDOW, n):
        seg_hi = max(btc_high[i - BTC_VOL_WINDOW:i])
        seg_lo = min(btc_low[i - BTC_VOL_WINDOW:i])
        base = btc_open[i - BTC_VOL_WINDOW]
        vol[i] = (seg_hi - seg_lo) / base * 100 if base > 0 else 0.0
    return vol


def find_signals_with_pnl(closes, highs):
    out = []
    n = len(closes)
    last = -10**9
    i = LOOKBACK
    while i < n - 1:
        if i - last < COOLDOWN_BARS:
            i += 1; continue
        past = closes[i - LOOKBACK]
        cur = closes[i]
        if past > 0 and (cur / past - 1) * 100 >= PUMP_PCT:
            entry = cur
            stop_price = entry * (1 + STOP_PCT / 100)
            end = min(i + 1 + HOLD, n)
            exit_price = None
            for j in range(i + 1, end):
                if highs[j] >= stop_price:
                    exit_price = stop_price
                    last = j
                    break
            if exit_price is None:
                exit_price = closes[end - 1]
                last = end - 1
            pnl = (1 - exit_price / entry) * 100 - COST
            out.append((i, pnl))
        i += 1
    return out


def main():
    btc_f = KDIR / "BTCUSDT_5m.json"
    btc_close, btc_high, btc_low, btc_open = load_ohlc(btc_f)
    n_btc = len(btc_close)
    btc_vol = btc_vol_series(btc_high, btc_low, btc_open, n_btc)

    files = sorted(glob.glob(str(KDIR / "*_5m.json")))
    print(f"데이터: {KDIR.name} ({len(files)}개 심볼)\n")

    rows = []  # (pnl, btc_vol_at_entry)
    for f in files:
        coin = Path(f).stem.replace("_5m", "")
        try:
            closes, highs, _, _ = load_ohlc(f)
        except Exception:
            continue
        if len(closes) < LOOKBACK + HOLD:
            continue
        for idx, pnl in find_signals_with_pnl(closes, highs):
            bv = btc_vol[idx] if idx < len(btc_vol) else 0.0
            rows.append((pnl, bv))

    if not rows:
        print("신호 없음")
        return

    vols = sorted(r[1] for r in rows if r[1] > 0)
    median_vol = vols[len(vols) // 2] if vols else 0

    low_regime = [r[0] for r in rows if r[1] <= median_vol]
    high_regime = [r[0] for r in rows if r[1] > median_vol]

    print(f"BTC 24h 변동폭 중앙값: {median_vol:.2f}%\n")
    print(f"{'레짐':<20}{'건수':>6}{'승률':>8}{'평균%':>9}{'합계%':>10}")
    for label, sub in [("평온장(중앙값 이하)", low_regime), ("변동장(중앙값 초과)", high_regime)]:
        if not sub:
            continue
        wins = sum(1 for p in sub if p > 0)
        wr = wins / len(sub) * 100
        mean = st.mean(sub)
        print(f"{label:<20}{len(sub):>6}{wr:>7.1f}%{mean:>8.2f}%{sum(sub):>9.1f}%")


if __name__ == "__main__":
    main()
