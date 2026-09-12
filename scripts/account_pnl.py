"""
계좌 실손익 — 2026-09-12 사용자 요청("달력에 반영, 수익 잘 안 된 거 같은데").

**봇 원장과 다른 것을 잰다. 둘 다 필요하다.**

| | 무엇을 재나 | 쓰는 곳 |
|---|---|---|
| `margin_short_ledger.csv` 등 | **봇 몫만** | 9/19·11/25 판정 (봇 전략 평가) |
| `pyramid_ledger.csv` | **사용자 추가분만** | 12/31 불타기 판정 |
| **이 스크립트** | **계좌 전체 실제 변동** | "오늘 실제로 얼마 벌었나" |

봇 원장이 사용자의 수동 불타기를 못 담는 것은 **결함이 아니라 설계**다 —
판정에 사용자 재량이 섞이면 봇 실력인지 사용자 판단인지 구분이 안 된다.
다만 "내 계좌가 실제로 얼마 늘었나"를 볼 장치가 없어서 혼란이 생겼다. 그걸 채운다.

계산 방법: 거래소가 주는 **실현손익·수수료·펀딩 원천 기록**을 그대로 합산한다.
  선물 = /fapi/v1/income (REALIZED_PNL, COMMISSION, FUNDING_FEE)
  마진 = 체결내역(매도 대금 − 매수 대금 − 수수료) + 이자

Run: .venv/Scripts/python.exe scripts/account_pnl.py [--days 7]
"""
import sys, os, json, argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
KST = timezone(timedelta(hours=9))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def JF(path, params=None):
    from bithumb.binance_guard import _signed
    r = _signed("GET", path, params or {})
    return r.json() if hasattr(r, "json") else json.loads(r)


def JM(path, params=None):
    from bithumb.margin_guard import _signed
    r = _signed("GET", path, params or {})
    return r.json() if hasattr(r, "json") else json.loads(r)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    start = int((datetime.now(KST) - timedelta(days=a.days)).timestamp() * 1000)

    day = defaultdict(lambda: defaultdict(float))
    # ── 선물: 거래소 income 원천 기록 ──
    got = 0
    cur = start
    while True:
        inc = JF("/fapi/v1/income", {"startTime": cur, "limit": 1000})
        if not isinstance(inc, list) or not inc:
            break
        for x in inc:
            d = datetime.fromtimestamp(x["time"] / 1000, KST).date()
            day[d][x["incomeType"]] += float(x["income"])
            day[d]["_선물"] += float(x["income"])
        got += len(inc)
        if len(inc) < 1000:
            break
        cur = inc[-1]["time"] + 1

    # ── 마진: 체결(매도−매수) + **상환(Repay) 비용** ──
    #   ★ 2026-09-12 수정: Repay로 갚으면 매수 체결이 남지 않아, 판 돈만 수익으로 잡혀
    #   마진 손익이 터무니없이 부풀었다(+195, +103). 상환 기록에 그때 가격을 곱해
    #   실제 지출로 반영한다.
    import csv, requests
    syms = set()
    for f in ("data/margin_short_ledger.csv", "data/margin_short_trades.csv"):
        pth = ROOT / f
        if not pth.exists(): continue
        for r in csv.DictReader(open(pth, encoding="utf-8")):
            try:
                if datetime.fromisoformat(r["exit_time"]).astimezone(KST) >=                    datetime.now(KST) - timedelta(days=a.days):
                    syms.add(r["symbol"])
            except Exception: pass

    def px_at(sym, ms_):
        try:
            k = requests.get("https://api.binance.com/api/v3/klines",
                             params={"symbol": sym, "interval": "1m",
                                     "startTime": ms_ - 60000, "limit": 2}, timeout=15).json()
            return float(k[-1][4]) if k else None
        except Exception:
            return None

    # ★ 2026-09-12 수정 2: 포지션이 날짜를 걸치면(9/11 매도 → 9/12 상환) 날짜별로
    #   +195 / -162로 쪼개져 오해를 낳는다. **청산(상환)일 기준으로 한 건을 통째로** 붙인다.
    for sy in sorted(syms):
        base = sy[:-4]
        flow = 0.0
        try:
            tr = JM("/sapi/v1/margin/myTrades", {"symbol": sy, "startTime": start, "limit": 500})
        except Exception:
            tr = []
        if isinstance(tr, list):
            for x in tr:
                q, pz = float(x["qty"]), float(x["price"])
                flow += q * pz * (-1 if x["isBuyer"] else 1)
                cm = float(x["commission"])
                flow -= cm * (pz if x["commissionAsset"] not in ("USDT",) else 1.0)
        close_d = None
        try:
            rp = JM("/sapi/v1/margin/repay", {"asset": base, "startTime": start, "size": 50})
            rows = rp.get("rows", []) if isinstance(rp, dict) else []
        except Exception:
            rows = []
        for x in rows:
            if x.get("status") != "CONFIRMED": continue
            ms_ = int(x["timestamp"])
            amt = float(x.get("amount") or x.get("principal") or 0)
            pz = px_at(sy, ms_)
            if pz is None or amt <= 0: continue
            flow -= amt * pz
            close_d = datetime.fromtimestamp(ms_ / 1000, KST).date()
        if abs(flow) < 0.01:
            continue
        if close_d is None and isinstance(tr, list) and tr:
            close_d = datetime.fromtimestamp(max(x["time"] for x in tr) / 1000, KST).date()
        if close_d is None:
            continue
        day[close_d]["_마진"] += flow

    ds = sorted(day)
    print("=" * 70)
    print("  계좌 실손익 — 거래소 원천 기록 기준 (봇 몫 + 수동 불타기 전부 포함)")
    print("=" * 70)
    print(f"{'날짜':<12}{'선물':>11}{'마진':>11}{'합계':>11}{'원(만)':>10}")
    tot = 0.0
    for d in ds:
        f_ = day[d].get("_선물", 0.0); m_ = day[d].get("_마진", 0.0)
        s_ = f_ + m_; tot += s_
        print(f"{str(d):<12}{f_:>+10.2f}{m_:>+10.2f}{s_:>+10.2f}{s_*1360/10000:>+9.1f}")
    print(f"{'합계':<12}{'':<22}{tot:>+10.2f}{tot*1360/10000:>+9.1f}")
    print()
    print("  선물 세부 (기간 합계)")
    agg = defaultdict(float)
    for d in ds:
        for k, v in day[d].items():
            if not k.startswith("_"): agg[k] += v
    for k, v in sorted(agg.items(), key=lambda z: -abs(z[1])):
        print(f"    {k:<22}{v:>+10.2f} USDT")
    print()
    print("  ※ 마진은 체결 대금 차액이다. Repay로 갚은 건은 체결이 안 남아")
    print("     반영되지 않을 수 있다(2026-09-12 TFUEL 사례). 그 경우 잔고 변화로 확인할 것.")
    print("  ※ 봇 판정(9/19·11/25)은 봇 원장을 쓴다. 이 표와 달라도 정상이다.")


if __name__ == "__main__":
    main()
