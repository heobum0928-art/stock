"""
자율#60 — 바이낸스 주식형 무기한선물: 밤사이 움직임(g) 뒤 미국 장 개장 1시간(r).
docs/PREREG_TRADFI_OVERNIGHT.md 그대로(커밋 54ced0b, 계산 전). 이 파일은 판정 기준을 바꾸지 않는다.

Run: .venv/Scripts/python.exe scripts/tradfi_overnight.py
캐시: research/tradfi_30m/<심볼>.pkl (재실행 시 받아둔 봉은 다시 받지 않고 이어받음)
산출: data/tradfi_overnight_trades.csv
"""
import sys, time, pickle, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "research" / "tradfi_30m"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data" / "tradfi_overnight_trades.csv"
FAPI = "https://fapi.binance.com"
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

ONBOARD_MAX = dt.datetime(2026, 7, 31, tzinfo=UTC)
G_MIN = 0.01
COST, COST2 = 0.0012, 0.0024
SEED, B = 20261019, 4000
HOLIDAYS = {dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16), dt.date(2026, 4, 3),
            dt.date(2026, 5, 25), dt.date(2026, 6, 19), dt.date(2026, 7, 3), dt.date(2026, 9, 7),
            dt.date(2026, 11, 26), dt.date(2026, 12, 25), dt.date(2025, 12, 25), dt.date(2025, 11, 27)}
ETFS = {"SPY", "QQQ", "EWY", "EWJ", "IWM", "XLE", "EWZ", "UVXY", "TQQQ", "SQQQ", "SOXL", "SOXS",
        "TZA", "TMF", "TBT", "KORU", "URNM", "XBI", "SMH", "EWT", "BITO"}   # 병기용 분류(판정에 안 씀)


def get(url, params, tries=6):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                time.sleep(5 * (i + 1))
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"요청 실패 {url} {params}")


def universe():
    info = get(f"{FAPI}/fapi/v1/exchangeInfo", {})
    out = []
    for s in info["symbols"]:
        if s.get("underlyingType") != "EQUITY" or s.get("status") != "TRADING":
            continue
        if not s["symbol"].endswith("USDT"):
            continue
        ob = dt.datetime.fromtimestamp(int(s["onboardDate"]) / 1000, UTC)
        if ob <= ONBOARD_MAX:
            out.append((s["symbol"], int(s["onboardDate"])))
    return sorted(out)


def load_klines(sym, start_ms):
    f = CACHE / f"{sym}.pkl"
    df = pickle.loads(f.read_bytes()) if f.exists() else None
    t = start_ms if df is None or df.empty else int(df.index[-1].timestamp() * 1000) + 1
    rows = []
    now_ms = int(time.time() * 1000)
    while t < now_ms:
        k = get(f"{FAPI}/fapi/v1/klines", dict(symbol=sym, interval="30m", startTime=t, limit=1500))
        if not k:
            break
        rows += [(x[0], float(x[4]), float(x[5])) for x in k]
        t = k[-1][0] + 1
        time.sleep(0.12)
        if len(k) < 1500:
            break
    if rows:
        new = pd.DataFrame(rows, columns=["t", "c", "v"])
        new.index = pd.to_datetime(new.pop("t"), unit="ms", utc=True)
        df = new if df is None or df.empty else pd.concat([df, new[~new.index.isin(df.index)]])
        df = df.sort_index()
        # 마지막 봉은 진행 중일 수 있으니 저장 전에 버린다(다음 실행에서 다시 받음)
        df = df.iloc[:-1]
        f.write_bytes(pickle.dumps(df))
    return df if df is not None else pd.DataFrame(columns=["c", "v"])


def trading_days(a, b):
    d, out = a, []
    while d <= b:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def bar(df, d, hh, mm):
    """ET 날짜 d의 hh:mm에 끝나는 30분봉 -> (종가, 거래량). 없으면 (nan, 0)."""
    end = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).astimezone(UTC)
    start = end - dt.timedelta(minutes=30)
    if start in df.index:
        row = df.loc[start]
        return row["c"], row["v"]
    return np.nan, 0.0


def block_boot(vals, blocks, rng, lo_pct=1.25, hi_pct=98.75):
    keys = np.unique(blocks)
    groups = {k: vals[blocks == k] for k in keys}
    out = np.empty(B)
    for i in range(B):
        pick = rng.choice(keys, len(keys), replace=True)
        out[i] = np.concatenate([groups[k] for k in pick]).mean()
    return np.percentile(out, lo_pct), np.percentile(out, hi_pct)     # 기본 97.5% CI


def main():
    uni = universe()
    print(f"대상 계약 {len(uni)}개 (EQUITY, TRADING, 상장일 ≤ 2026-07-31, USDT)")
    last_day = (dt.datetime.now(UTC) - dt.timedelta(hours=20)).astimezone(NY).date()
    recs = []
    for i, (sym, ob) in enumerate(uni, 1):
        df = load_klines(sym, ob)
        if df.empty:
            continue
        first = df.index[0].astimezone(NY).date()
        days = trading_days(first - dt.timedelta(days=7), last_day)
        for j in range(1, len(days)):
            d, p = days[j], days[j - 1]
            if d < first + dt.timedelta(days=1):
                continue
            c0, v0 = bar(df, d, 9, 30)
            c1, v1 = bar(df, d, 10, 30)
            cp, vp = bar(df, p, 16, 0)
            if not (v0 > 0 and v1 > 0 and vp > 0) or np.isnan(c0 + c1 + cp):
                continue
            recs.append((sym.replace("USDT", ""), d.isoformat(), c0 / cp - 1, c1 / c0 - 1))
        if i % 20 == 0:
            print(f"  ... {i}/{len(uni)} 계약 처리")
    allr = pd.DataFrame(recs, columns=["sym", "date", "g", "r"])
    allr["wk"] = pd.to_datetime(allr["date"]).dt.strftime("%G-%V")
    allr["D"] = np.sign(allr["g"]) * allr["r"]
    allr["etf"] = allr["sym"].isin(ETFS)
    tr = allr[allr["g"].abs() >= G_MIN].copy()
    tr.to_csv(OUT, index=False)

    print("=" * 70)
    print(f"계약-일 {len(allr)}건 중 |g|≥{G_MIN*100:.0f}% 거래 {len(tr)}건 / 계약 {tr['sym'].nunique()}개 / "
          f"기간 {tr['date'].min()} ~ {tr['date'].max()} / 주 {tr['wk'].nunique()}개")
    print("잣대: 명목가 기준 수익률(비용 전), 순수익은 왕복 0.12% 차감")
    print("=" * 70)
    if len(tr) < 10:
        print("표본 없음")
        return
    D = tr["D"].values
    Dbar = D.mean()
    d = 1 if Dbar > 0 else -1
    gross = d * D
    net = gross - COST
    blocks = tr["wk"].values
    rng = np.random.default_rng(SEED)
    glo, ghi = block_boot(gross, blocks, rng)
    rng = np.random.default_rng(SEED)
    nlo, nhi = block_boot(net, blocks, rng)

    dates = pd.to_datetime(tr["date"])
    mid = dates.median()
    h1, h2 = (dates <= mid).values, (dates > mid).values
    byc = pd.Series(net).groupby(tr["sym"].values).sum()
    top = byc.idxmax()
    keep = (tr["sym"] != top).values

    t1 = len(tr) >= 300
    t2 = glo > 0
    t3 = net.mean() > 0 and nlo > 0
    t4 = all(gross[h].mean() > 0 and net[h].mean() > 0 for h in (h1, h2))
    t5 = (gross - COST2).mean() > 0
    t6 = net[keep].mean() > 0

    print(f"방향 d = {'+1 추세(밤사이 방향 따라감)' if d > 0 else '-1 반전(밤사이 방향 반대로)'}  (D̄ = {Dbar*100:+.4f}%)")
    print(f"  T1 거래 건수           {len(tr)}                              → {'충족' if t1 else '미충족'}")
    print(f"  T2 총수익 평균          {gross.mean()*100:+.4f}%  97.5% CI [{glo*100:+.4f}, {ghi*100:+.4f}]  → {'충족' if t2 else '미충족'}")
    print(f"  T3 순수익 평균(−0.12%)  {net.mean()*100:+.4f}%  97.5% CI [{nlo*100:+.4f}, {nhi*100:+.4f}]  → {'충족' if t3 else '미충족'}")
    print(f"  T4 전반/후반            총 {gross[h1].mean()*100:+.4f}% / {gross[h2].mean()*100:+.4f}%  순 {net[h1].mean()*100:+.4f}% / {net[h2].mean()*100:+.4f}%  → {'충족' if t4 else '미충족'}")
    print(f"  T5 비용 2배(0.24%) 순평균 {(gross-COST2).mean()*100:+.4f}%                      → {'충족' if t5 else '미충족'}")
    print(f"  T6 최대기여 계약 {top} 제외 순평균 {net[keep].mean()*100:+.4f}%                → {'충족' if t6 else '미충족'}")
    allok = t1 and t2 and t3 and t4 and t5 and t6
    print(f"\n  → 판정: {'**전방 검증 후보** (실거래 변경 없음)' if allok else '기각'}")

    print("\n[병기 — 판정에 안 씀]")
    print(f"  승률 {(gross>0).mean()*100:.1f}%  중앙 {np.median(gross)*100:+.4f}%  최악5평균 {np.sort(gross)[:5].mean()*100:+.2f}%  최대손실 {gross.min()*100:+.2f}%")
    cs = pd.Series(gross).groupby(tr["sym"].values).agg(["mean", "count"])
    cs = cs[cs["count"] >= 3]
    print(f"  계약별 양(+) 비율 {(cs['mean']>0).mean()*100:.0f}% ({len(cs)}개, 건수 3 이상)")
    for lab, m in (("ETF", tr["etf"].values), ("단일주식", ~tr["etf"].values)):
        if m.sum():
            print(f"  {lab}: {int(m.sum())}건 총 {gross[m].mean()*100:+.4f}% 순 {net[m].mean()*100:+.4f}%")
    mon = (pd.to_datetime(tr["date"]).dt.weekday == 0).values
    if mon.sum():
        print(f"  월요일(주말 뒤): {int(mon.sum())}건 총 {gross[mon].mean()*100:+.4f}% / 그 외 {int((~mon).sum())}건 {gross[~mon].mean()*100:+.4f}%")
    for lab, sel in (("g>0(밤새 오름)", (tr['g'] > 0).values), ("g<0(밤새 내림)", (tr['g'] < 0).values)):
        print(f"  {lab}: {int(sel.sum())}건 d적용 총 {gross[sel].mean()*100:+.4f}%")
    a = allr
    print(f"  [문턱 없이 모든 날] {len(a)}건 D̄ {a['D'].mean()*100:+.4f}% (d 적용 {d*a['D'].mean()*100:+.4f}%)")
    print(f"  |g| 평균 {tr['g'].abs().mean()*100:.2f}%  |r| 평균 {tr['r'].abs().mean()*100:.2f}%")


def main_forward():
    """docs/PREREG_TRADFI_OVERNIGHT_FWD.md — 2026-10-20 이후 새 데이터만, 방향 반전(d=-1) 고정, 95% CI.
    계산은 2026-11-30에 한 번만(사전등록 5절). 계약 목록은 docs/tradfi_overnight_universe.txt 고정."""
    syms = [x.strip() for x in (ROOT / "docs" / "tradfi_overnight_universe.txt").read_text(encoding="utf-8").split() if x.strip()]
    onb = {s: ob for s, ob in universe()}
    FWD_START = dt.date(2026, 10, 20)
    last_day = (dt.datetime.now(UTC) - dt.timedelta(hours=20)).astimezone(NY).date()
    recs = []
    for sym in syms:
        df = load_klines(sym, onb.get(sym, 0))
        if df.empty:
            continue
        days = trading_days(FWD_START - dt.timedelta(days=7), last_day)
        for j in range(1, len(days)):
            d, p = days[j], days[j - 1]
            if d < FWD_START:
                continue
            c0, v0 = bar(df, d, 9, 30)
            c1, v1 = bar(df, d, 10, 30)
            cp, vp = bar(df, p, 16, 0)
            if not (v0 > 0 and v1 > 0 and vp > 0) or np.isnan(c0 + c1 + cp):
                continue
            recs.append((sym.replace("USDT", ""), d.isoformat(), c0 / cp - 1, c1 / c0 - 1))
    allr = pd.DataFrame(recs, columns=["sym", "date", "g", "r"])
    tr = allr[allr["g"].abs() >= G_MIN].copy()
    print("=" * 70)
    print(f"[전방] 계약-일 {len(allr)}건 중 |g|≥1% 거래 {len(tr)}건 / 기간 {FWD_START} ~ {last_day} / 방향 반전 고정")
    print("잣대: 명목가 기준 수익률, 순수익은 왕복 0.12% 차감")
    print("=" * 70)
    if len(tr) == 0:
        print("표본 없음")
        return
    tr["wk"] = pd.to_datetime(tr["date"]).dt.strftime("%G-%V")
    gross = (-np.sign(tr["g"]) * tr["r"]).values
    net = gross - COST
    blocks = tr["wk"].values
    rng = np.random.default_rng(20261020)
    glo, ghi = block_boot(gross, blocks, rng, 2.5, 97.5)
    rng = np.random.default_rng(20261020)
    nlo, nhi = block_boot(net, blocks, rng, 2.5, 97.5)
    dates = pd.to_datetime(tr["date"])
    mid = dates.median()
    h1, h2 = (dates <= mid).values, (dates > mid).values
    byc = pd.Series(net).groupby(tr["sym"].values).sum()
    top = byc.idxmax()
    keep = (tr["sym"] != top).values
    f1 = len(tr) >= 300
    f2 = glo > 0
    f3 = net.mean() > 0 and nlo > 0
    f4 = (gross - COST2).mean() > 0
    f5 = all(net[h].mean() > 0 for h in (h1, h2) if h.sum())
    f6 = net[keep].mean() > 0
    print(f"  F1 거래 건수 {len(tr)}                         → {'충족' if f1 else '미충족'}")
    print(f"  F2 총수익 평균 {gross.mean()*100:+.4f}%  95% CI [{glo*100:+.4f}, {ghi*100:+.4f}]  → {'충족' if f2 else '미충족'}")
    print(f"  F3 순수익 평균 {net.mean()*100:+.4f}%  95% CI [{nlo*100:+.4f}, {nhi*100:+.4f}]  → {'충족' if f3 else '미충족'}")
    print(f"  F4 비용 2배 순평균 {(gross-COST2).mean()*100:+.4f}%               → {'충족' if f4 else '미충족'}")
    print(f"  F5 전반/후반 순평균 {net[h1].mean()*100:+.4f}% / {net[h2].mean()*100:+.4f}%  → {'충족' if f5 else '미충족'}")
    print(f"  F6 최대기여 {top} 제외 순평균 {net[keep].mean()*100:+.4f}%     → {'충족' if f6 else '미충족'}")
    ok = f1 and f2 and f3 and f4 and f5 and f6
    if not f1:
        verdict = "판별 불가(건수 부족) — 사전등록상 1회만 2026-12-31까지 연장"
    else:
        verdict = "**채택 후보** (실거래 변경 없음, 체결 가능성 별도 확인)" if ok else "기각"
    print(f"\n  → 판정: {verdict}")
    print(f"  [병기] 승률 {(gross>0).mean()*100:.1f}% 중앙 {np.median(gross)*100:+.4f}% 최악5평균 {np.sort(gross)[:5].mean()*100:+.2f}%")


if __name__ == "__main__":
    if "--forward" in sys.argv:
        main_forward()
    else:
        main()
