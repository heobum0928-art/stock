"""
자율#61 — 한국 대형 우량주: 거래대금 상위 5 중 음봉 다음 날 시가 매수, +5% 익절 / -2% 손절 / 종가 청산.
docs/PREREG_KR_BLUECHIP_DIP.md 그대로. 모의 시험(주문 없음). 일봉 출처: 네이버 증권 fchart.

Run: .venv/Scripts/python.exe scripts/kr_bluechip_dip.py
캐시: research/kr_daily/<코드>.csv, 대상 목록: research/kr_daily/universe.txt (처음 실행 시 확정 후 고정)
"""
import sys, re, time
from pathlib import Path
import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "research" / "kr_daily"
CACHE.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0"}
TOPN, PICK = 100, 5
TP, SL = 0.05, 0.02
COST, COST2 = 0.0025, 0.005
SEED, B = 20261022, 4000


def universe():
    f = CACHE / "universe.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").split()
    r = requests.get(f"https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize={TOPN}", headers=H, timeout=30)
    codes = [s["itemCode"] for s in r.json()["stocks"]]
    codes = codes[:TOPN]
    f.write_text("\n".join(codes), encoding="utf-8")
    return codes


def daily(code):
    f = CACHE / f"{code}.csv"
    if f.exists():
        return pd.read_csv(f, parse_dates=["date"])
    r = requests.get("https://fchart.stock.naver.com/sise.nhn",
                     params=dict(symbol=code, timeframe="day", count=1500, requestType=0), headers=H, timeout=30)
    rows = []
    for m in re.finditer(r'item data="(\d{8})\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)"', r.text):
        d, o, h, l, c, v = m.groups()
        rows.append((d, int(o), int(h), int(l), int(c), int(v)))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df.to_csv(f, index=False)
    time.sleep(0.15)
    return df


def block_boot(vals, blocks, rng):
    keys = np.unique(blocks)
    groups = {k: vals[blocks == k] for k in keys}
    out = np.empty(B)
    for i in range(B):
        pick = rng.choice(keys, len(keys), replace=True)
        out[i] = np.concatenate([groups[k] for k in pick]).mean()
    return np.percentile(out, 2.5), np.percentile(out, 97.5)


def main():
    codes = universe()
    print(f"대상 {len(codes)}개 (코스피 시총 상위, 현재 순위 — 생존 편향 있음)")
    frames = []
    for c in codes:
        df = daily(c)
        if df.empty:
            continue
        df["code"] = c
        frames.append(df)
    d = pd.concat(frames, ignore_index=True)
    d = d[(d.open > 0) & (d.volume > 0)]
    last = d["date"].max()
    start = last - pd.DateOffset(years=5)
    d = d[d["date"] >= start].sort_values(["code", "date"]).reset_index(drop=True)
    d["value"] = d["close"] * d["volume"]
    # 다음 거래일 시가·고가·저가·종가 (같은 종목 안에서)
    for col in ("open", "high", "low", "close"):
        d["n_" + col] = d.groupby("code")[col].shift(-1)
    d["n_date"] = d.groupby("code")["date"].shift(-1)
    d["rank"] = d.groupby("date")["value"].rank(ascending=False, method="first")
    sig = d[(d["rank"] <= PICK) & (d["close"] < d["open"]) & d["n_open"].notna()].copy()

    e = sig["n_open"].values
    tp_hit = sig["n_high"].values >= e * (1 + TP)
    sl_hit = sig["n_low"].values <= e * (1 - SL)
    gross = np.where(sl_hit, -SL, np.where(tp_hit, TP, sig["n_close"].values / e - 1))
    reason = np.where(sl_hit, "손절", np.where(tp_hit, "익절", "종가"))
    sig["gross"], sig["reason"] = gross, reason
    sig["net"], sig["net2"] = gross - COST, gross - COST2

    day = sig.groupby("n_date").agg(net=("net", "mean"), net2=("net2", "mean"), n=("net", "size")).reset_index()
    alld = pd.Series(sorted(d["date"].unique()))
    print(f"기간 {start.date()} ~ {last.date()} | 신호 거래 {len(sig)}건 | 신호가 있는 날 {len(day)}일 / 전체 {len(alld)}일")
    print("잣대: 명목가(투자금) 대비 수익률, 비용 0.25% 차감(민감도 0.5%)")
    print("=" * 66)

    x = day["net"].values
    month = day["n_date"].dt.strftime("%Y-%m").values
    rng = np.random.default_rng(SEED)
    lo, hi = block_boot(x, month, rng)
    mid = day["n_date"].median()
    h1, h2 = (day["n_date"] <= mid).values, (day["n_date"] > mid).values
    hh1, hh2 = x[h1].mean(), x[h2].mean()
    h1_ok = len(day) >= 300
    h2_ok = lo > 0
    h3_ok = hh1 > 0 and hh2 > 0
    h4_ok = day["net2"].mean() > 0
    print(f"  H1 신호가 있는 날 수     {len(day)}                       → {'충족' if h1_ok else '미충족'}")
    print(f"  H2 평균 일 순수익        {x.mean()*100:+.4f}%  95% CI [{lo*100:+.4f}, {hi*100:+.4f}]  → {'충족' if h2_ok else '미충족'}")
    print(f"  H3 전반/후반             {hh1*100:+.4f}% / {hh2*100:+.4f}%     → {'충족' if h3_ok else '미충족'}")
    print(f"  H4 비용 0.5% 평균        {day['net2'].mean()*100:+.4f}%              → {'충족' if h4_ok else '미충족'}")
    ok = h1_ok and h2_ok and h3_ok and h4_ok
    print(f"\n  → 판정: {'**모의 후보** (실거래 아님, 독립 검증 필요)' if ok else '기각'}")

    print("\n[H5 사용자 목표 2%/일 — 보고]")
    # 신호가 없는 날은 수익 0으로 전체 일수에 포함
    full = pd.Series(0.0, index=alld)
    full.loc[day["n_date"].values] = day["net"].values
    ann_days = 252
    mean_all = full.mean()
    print(f"  거래한 날 평균 {x.mean()*100:+.3f}% | 전체 일수 평균(신호 없는 날 0) {mean_all*100:+.4f}%/일")
    print(f"  하루 수익 ≥ 2%인 날: 거래한 날의 {(x>=0.02).mean()*100:.1f}% ({int((x>=0.02).sum())}일)")
    comp = np.prod(1 + full.values)
    yrs = len(full) / ann_days
    print(f"  5년 복리 누적 {comp:.3f}배 (연 {comp**(1/yrs)-1:+.1%}) | 단리 합 {full.sum()*100:+.1f}%")
    print(f"  2% 목표({'달성' if x.mean()>=0.02 else '불가'}): 평균이 2%에 {'도달' if x.mean()>=0.02 else '못 미침'}")

    print("\n[병기 — 판정에 안 씀]")
    t = sig["net"].values
    w, l = t[t > 0], t[t <= 0]
    print(f"  거래 단위 승률 {(t>0).mean()*100:.1f}% | 이길 때 {w.mean()*100:+.2f}% / 질 때 {l.mean()*100:+.2f}% | 손익비 {abs(w.mean()/l.mean()):.2f}")
    rc = pd.Series(sig['reason']).value_counts(normalize=True)
    print("  청산 비율: " + ", ".join(f"{k} {v*100:.0f}%" for k, v in rc.items()))
    print(f"  최악 5일 평균 {np.sort(x)[:5].mean()*100:+.2f}% | 최대손실일 {x.min()*100:+.2f}%")
    yr = pd.Series(x).groupby(day["n_date"].dt.year.values).agg(["mean", "count"])
    print("  연도별: " + ", ".join(f"{int(k)} {v['mean']*100:+.3f}%({int(v['count'])}일)" for k, v in yr.iterrows()))
    print(f"  총수익(비용 전) 거래 평균 {sig['gross'].mean()*100:+.4f}%")


if __name__ == "__main__":
    main()
