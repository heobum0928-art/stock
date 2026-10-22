"""
친구 규칙 한국 대형주 모의 프로그램 (주문 없음, 모의 자본만 계산) — docs/PREREG_KR_BLUECHIP_DIP.md / PREREG_KR_DIP_FWD.md.

규칙(고정): 대상 = 코스피 시총 상위 100(research/kr_daily/universe.txt 고정 목록)
  신호일 t: 그날 거래대금(종가×거래량) 상위 5 중 음봉(종가<시가) → 다음 거래일 시가 매수
  청산(같은 날): +5% 닿으면 익절, -2% 닿으면 손절(둘 다 닿으면 손절 먼저), 아니면 종가. 비용 왕복 0.25%.
설정(아래 상수): 투자금 상한(INVEST_CAP), 복리 여부(COMPOUND). 규칙 숫자는 바꾸지 않는다.

사용: .venv/Scripts/python.exe scripts/kr_dip_paper.py
  - 시세를 새로 받아 2026-10-23 이후 거래일을 모의로 정산하고(이미 한 날은 건너뜀), 요약과 "다음 거래일 매수 후보"를 출력한다.
  - 장 마감(15:30) 이후에 돌리면 오늘 결과까지 반영된다.
"""
import sys, re, json, time
import datetime as dt
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
STATE = ROOT / "data" / "kr_dip_paper_state.json"
TRADES = ROOT / "data" / "kr_dip_paper_trades.csv"
H = {"User-Agent": "Mozilla/5.0"}

# ── 설정(사용자 지정) ───────────────────────────
INIT_CAPITAL = 10_000_000      # 모의 시작 자본(원)
INVEST_CAP = 10_000_000        # 하루 투자금 상한(원). 자본이 이보다 커도 이 금액까지만 투자
COMPOUND = True                # True: 자본이 늘면 그만큼 투자(상한까지) / False: 항상 INIT_CAPITAL만 투자
START = dt.date(2026, 10, 23)  # 이 날짜 이후 거래일만 모의 정산(설계 이후 새 데이터)
# ── 규칙(고정) ────────────────────────────────
PICK, TP, SL, COST = 5, 0.05, 0.02, 0.0025


def names():
    try:
        r = requests.get("https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=100", headers=H, timeout=30)
        return {s["itemCode"]: s["stockName"] for s in r.json()["stocks"]}
    except Exception:
        return {}


def refresh(code):
    """캐시된 일봉에 최근 60일을 덧붙인다."""
    f = CACHE / f"{code}.csv"
    old = pd.read_csv(f, parse_dates=["date"]) if f.exists() else pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    r = requests.get("https://fchart.stock.naver.com/sise.nhn",
                     params=dict(symbol=code, timeframe="day", count=60, requestType=0), headers=H, timeout=30)
    rows = [(a, int(b), int(c), int(d), int(e), int(g)) for a, b, c, d, e, g in
            re.findall(r'item data="(\d{8})\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)"', r.text)]
    new = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    new["date"] = pd.to_datetime(new["date"])
    df = pd.concat([old, new]).drop_duplicates("date", keep="last").sort_values("date")
    df.to_csv(f, index=False)
    time.sleep(0.1)
    return df


def main():
    codes = (CACHE / "universe.txt").read_text(encoding="utf-8").split()
    nm = names()
    frames = []
    for c in codes:
        try:
            df = refresh(c)
        except Exception as e:
            print(f"[경고] {c} 시세 실패: {e}")
            continue
        df = df[(df.open > 0) & (df.volume > 0)].copy()
        df["code"] = c
        frames.append(df)
    d = pd.concat(frames, ignore_index=True).sort_values(["code", "date"]).reset_index(drop=True)
    d["value"] = d["close"] * d["volume"]
    d["rank"] = d.groupby("date")["value"].rank(ascending=False, method="first")
    last_day = d["date"].max()

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"capital": INIT_CAPITAL, "done": []}
    done = set(state["done"])
    days = sorted(d["date"].unique())
    traded = []
    for i in range(1, len(days)):
        T, P = days[i], days[i - 1]
        if T.date() < START or str(T.date()) in done:
            continue
        picks = d[(d["date"] == P) & (d["rank"] <= PICK) & (d["close"] < d["open"])]
        today = d[d["date"] == T].set_index("code")
        rets = []
        for _, p in picks.iterrows():
            if p["code"] not in today.index:
                continue
            row = today.loc[p["code"]]
            e = float(row["open"])
            if row["low"] <= e * (1 - SL):
                g, why = -SL, "손절"
            elif row["high"] >= e * (1 + TP):
                g, why = TP, "익절"
            else:
                g, why = row["close"] / e - 1, "종가"
            rets.append((p["code"], e, why, g - COST))
        base = min(state["capital"], INVEST_CAP) if COMPOUND else min(INIT_CAPITAL, INVEST_CAP)
        day_ret = float(np.mean([r[3] for r in rets])) if rets else 0.0
        pnl = base * day_ret
        state["capital"] = state["capital"] + pnl
        for code, e, why, net in rets:
            traded.append((str(T.date()), code, nm.get(code, ""), e, why, round(net * 100, 3), round(base / max(len(rets), 1)), ))
        state["done"].append(str(T.date()))
        done.add(str(T.date()))
        print(f"{T.date()} 정산: 거래 {len(rets)}건, 하루 수익 {day_ret*100:+.2f}%, 손익 {pnl:+,.0f}원, 모의 자본 {state['capital']:,.0f}원")
    if traded:
        out = pd.DataFrame(traded, columns=["date", "code", "name", "entry", "exit_reason", "net_pct", "alloc_krw"])
        out.to_csv(TRADES, mode="a", header=not TRADES.exists(), index=False)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 62)
    cap = state["capital"]
    print(f"[모의 현황] 시작 {INIT_CAPITAL:,}원 → 현재 {cap:,.0f}원 ({(cap/INIT_CAPITAL-1)*100:+.2f}%) | 정산한 날 {len(state['done'])}일 | 복리 {'켬' if COMPOUND else '끔'} | 투자 상한 {INVEST_CAP:,}원")
    print(f"시세 최신일 {last_day.date()} (모의 정산 시작일 {START})")
    nxt = d[(d["date"] == last_day) & (d["rank"] <= PICK)].sort_values("rank")
    print(f"\n[다음 거래일({last_day.date()} 장 마감 기준) 매수 후보 — 음봉인 것만]")
    c = 0
    for _, p in nxt.iterrows():
        mark = "매수 후보" if p["close"] < p["open"] else "양봉이라 제외"
        c += p["close"] < p["open"]
        print(f"  거래대금 {int(p['rank'])}위 {nm.get(p['code'], p['code'])}({p['code']}) 시가 {p['open']:,.0f} → 종가 {p['close']:,.0f} : {mark}")
    print(f"→ 내일 시가에 사는 후보 {c}개. 익절 +5% / 손절 -2% / 아니면 종가에 정리(모의, 실제 주문 아님)")


if __name__ == "__main__":
    main()
