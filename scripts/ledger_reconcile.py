"""
거래소 원장 대조 (ledger_reconcile) — 읽기전용, 주문 API 미호출. 2026-08-19.

배경: 2026-08-19에 봇의 손익기록(data/margin_short_trades.csv)이 거래소 실제와
다르다는 것이 발견됨. 원인 셋:
  ① 펀딩비가 전혀 기록 안 됨 — 46건 기간 -41.08 USDT(EV의 약 20% 잠식)
  ② 수수료도 기록 안 됨 — -2.57 USDT
  ③ 청산가를 현물(spot) 시세로 기록 — 체결은 선물인데. basis 영향 +14.31 USDT(유리 방향)
순 왜곡 -29.03 USDT. 그 결과 EV가 +9.60%(CSV)로 나오지만 실제는 +7.41%였다.

이 스크립트는 실거래 봇을 **전혀 건드리지 않고**, 거래소 원장(/fapi/v1/income,
/fapi/v1/userTrades)을 긁어와 거래별로 매칭한 "진짜 손익표"를 따로 만든다.
봇 코드 수정은 51건 동결 해제 후로 미루되, 그때까지 실제 성적을 모르고 지나가는
일이 없게 하는 것이 목적이다.

★ 읽기전용: GET만 호출. 주문·취소·설정변경 일절 없음.
출력 data/margin_short_ledger.csv | 로그 logs/ledger_reconcile.log
Run: python scripts/ledger_reconcile.py  (하루 1회 스케줄러 호출 상정)
"""
import sys, csv, json, time, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [LEDGER] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(ROOT / "logs" / "ledger_reconcile.log", encoding="utf-8")])
log = logging.getLogger(__name__)

from bithumb.binance_guard import _signed

KST = timezone(timedelta(hours=9))
TRADES_CSV = ROOT / "data" / "margin_short_trades.csv"
OUT_CSV    = ROOT / "data" / "margin_short_ledger.csv"
START_MS   = int(datetime(2026, 7, 20, tzinfo=KST).timestamp() * 1000)

# 봇 기록과 원장 순손익 차이가 이 이상이면 알림(누적 기준, USDT)
ALERT_DIFF_USDT = 20.0

OUT_FIELDS = ["entry_time", "exit_time", "symbol", "margin_usdt",
              "csv_pnl_usdt", "realized_pnl", "funding_usdt", "commission_usdt",
              "net_pnl_usdt", "net_pnl_pct_margin", "diff_vs_csv", "reason"]


def fetch_income():
    """전체 income 원장 — 7일 단위 페이지네이션(API 상한 회피)."""
    rows, cur, end = [], START_MS, int(time.time() * 1000)
    while cur < end:
        r = _signed("GET", "/fapi/v1/income",
                    {"startTime": cur, "endTime": min(cur + 7 * 86400000, end), "limit": 1000})
        if r.status_code != 200:
            raise RuntimeError(f"income 조회 실패 {r.status_code}: {r.text[:200]}")
        rows += r.json()
        cur += 7 * 86400000
        time.sleep(0.3)
    return rows


def load_csv_trades():
    """봇 기록. ragged CSV(16/18필드 혼재)라 DictReader 사용 — pandas 금지."""
    if not TRADES_CSV.exists():
        return []
    with open(TRADES_CSV, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("exit_time")]


def to_ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def main():
    trades = load_csv_trades()
    if not trades:
        log.info("봇 거래기록 없음 — 종료")
        return
    log.info(f"봇 기록 {len(trades)}건 로드")

    try:
        income = fetch_income()
    except Exception as e:
        log.error(f"원장 조회 실패: {e}")
        return
    log.info(f"거래소 원장 {len(income)}행 수집")

    # 심볼별 시간순 인덱싱
    by_sym = {}
    for x in income:
        s = x.get("symbol")
        if not s:
            continue
        by_sym.setdefault(s, []).append(
            (int(x["time"]), x["incomeType"], float(x["income"])))
    for v in by_sym.values():
        v.sort()

    out, used, unmatched = [], set(), 0
    tot_csv = tot_net = 0.0

    for t in sorted(trades, key=lambda r: r["exit_time"]):
        sym = t["symbol"]
        try:
            e_ms, x_ms = to_ms(t["entry_time"]), to_ms(t["exit_time"])
        except Exception:
            unmatched += 1
            continue
        margin = float(t.get("margin_usdt") or 0) or 30.0
        csv_pnl = float(t.get("pnl_usdt") or 0)

        # 청산은 CSV 기록보다 늦게 찍힌 사례가 있음(서버측스탑 최대 8.5h) → 뒤로 여유 12h
        lo, hi = e_ms - 60_000, x_ms + 12 * 3600_000
        realized = funding = comm = 0.0
        for i, (ts, typ, inc) in enumerate(by_sym.get(sym, [])):
            key = (sym, i)
            if key in used or not (lo <= ts <= hi):
                continue
            if typ == "REALIZED_PNL":
                realized += inc; used.add(key)
            elif typ == "FUNDING_FEE":
                funding += inc; used.add(key)
            elif typ == "COMMISSION":
                comm += inc; used.add(key)

        if realized == 0 and funding == 0 and comm == 0:
            unmatched += 1

        net = realized + funding + comm
        tot_csv += csv_pnl; tot_net += net
        out.append(dict(
            entry_time=t["entry_time"], exit_time=t["exit_time"], symbol=sym,
            margin_usdt=margin, csv_pnl_usdt=round(csv_pnl, 3),
            realized_pnl=round(realized, 4), funding_usdt=round(funding, 4),
            commission_usdt=round(comm, 4), net_pnl_usdt=round(net, 3),
            net_pnl_pct_margin=round(net / margin * 100, 2) if margin else "",
            diff_vs_csv=round(net - csv_pnl, 3), reason=t.get("reason", "")))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader(); w.writerows(out)

    wins = sum(1 for r in out if r["net_pnl_usdt"] > 0)
    margins = sum(r["margin_usdt"] for r in out) or 1
    log.info(f"대조 완료 {len(out)}건(미매칭 {unmatched}) → {OUT_CSV.name}")
    log.info(f"  봇 기록 합계 {tot_csv:+.2f} / 원장 실제 {tot_net:+.2f} "
             f"(차이 {tot_net - tot_csv:+.2f})")
    log.info(f"  원장기준 승률 {wins}/{len(out)} = {wins/len(out)*100:.1f}%, "
             f"EV(자본가중) {tot_net/margins*100:+.2f}%")

    diff = abs(tot_net - tot_csv)
    if diff >= ALERT_DIFF_USDT:
        msg = (f"📒 원장대조: 봇기록 {tot_csv:+.1f} vs 실제 {tot_net:+.1f} USDT "
               f"(차이 {tot_net - tot_csv:+.1f})\n"
               f"원장기준 EV {tot_net/margins*100:+.2f}%, 승률 {wins}/{len(out)}")
        try:
            from bithumb import notify
            notify.send(msg)
        except Exception as e:
            log.warning(f"알림 전송 실패: {e}")


if __name__ == "__main__":
    main()
