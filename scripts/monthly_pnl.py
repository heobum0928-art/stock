"""
월별 실거래 손익표 — docs/RESEARCH_SCORECARD.md 2절. 거래소 income 내역(실현손익+수수료+펀딩, 입출금 제외) 기준.
롱 = BTC·ETH·SOL 심볼(core_lev·trend3), 숏 = 그 외 심볼(숏 봇). 근사 분류다 — 숏 봇이 BTC/ETH/SOL을 거래하면 롱으로 잡힌다.
기준 시각 이후 합계(판정용)와 현재 평가손익도 같이 낸다.
Run: .venv/Scripts/python.exe scripts/monthly_pnl.py [시작일 YYYY-MM-DD, 기본 2026-08-01]
"""
import sys, json, datetime as dt, collections
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bithumb.binance_guard import _signed

KST = dt.timezone(dt.timedelta(hours=9))
LONGS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
start = dt.datetime.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-08-01").replace(tzinfo=KST)
BASE = json.loads((ROOT / "data" / "loss_stop_baseline.json").read_text(encoding="utf-8"))
base_ms = int(dt.datetime.fromisoformat(BASE["recorded_at_kst"]).timestamp() * 1000)


def income(since_ms):
    rows, t = [], since_ms
    while True:
        r = _signed("GET", "/fapi/v1/income", {"startTime": t, "limit": 1000})
        if r.status_code != 200:
            raise RuntimeError(f"income 조회 실패 {r.status_code} {r.text[:100]}")
        x = r.json()
        rows += x
        if len(x) < 1000:
            return rows
        t = int(x[-1]["time"]) + 1


def main():
    # income API는 7일 단위 제한이 없지만 오래된 구간은 비어 있을 수 있어 월 단위로 이어 받는다.
    rows = income(int(start.timestamp() * 1000))
    m = collections.defaultdict(lambda: collections.Counter())
    since_base = 0.0
    for x in rows:
        if x["incomeType"] not in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
            continue
        v = float(x["income"])
        k = dt.datetime.fromtimestamp(int(x["time"]) / 1000, KST).strftime("%Y-%m")
        side = "롱" if x.get("symbol") in LONGS else "숏"
        m[k][side] += v
        m[k]["합계"] += v
        if int(x["time"]) >= base_ms:
            since_base += v
    print("월별 실거래 순손익 (USDT, 실현+수수료+펀딩, 입출금 제외)")
    print(f"{'월':8}{'롱':>10}{'숏':>10}{'합계':>10}")
    for k in sorted(m):
        c = m[k]
        print(f"{k:8}{c['롱']:>+10.1f}{c['숏']:>+10.1f}{c['합계']:>+10.1f}")
    tot = sum(c["합계"] for c in m.values())
    print(f"{'전체':8}{sum(c['롱'] for c in m.values()):>+10.1f}{sum(c['숏'] for c in m.values()):>+10.1f}{tot:>+10.1f}")
    a = _signed("GET", "/fapi/v2/account").json()
    print(f"\n현재 평가손익(미실현): {float(a['totalUnrealizedProfit']):+.2f} | 지갑 {float(a['totalWalletBalance']):.1f}")
    print(f"[판정용] 기준 시각({BASE['recorded_at_kst']}) 이후 순손익 합계: {since_base:+.2f} USDT  (합격선 12-31까지 0 이상)")


if __name__ == "__main__":
    main()
