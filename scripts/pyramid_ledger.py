"""
불타기(추가 진입) 원장 — docs/PREREG_PYRAMID.md 기준. 2026-09-09.

**읽기 전용. 주문·설정 변경 없음. 봇 로직도 건드리지 않는다.**
`/fapi/v1/userTrades`로 체결을 소급 재구성해 최초 진입분과 추가 진입분을 분리한다.

분류(사전등록 §1, 결과 보고 변경 금지):
  진입~청산 구간의 체결을 시간순으로 놓고
    첫 SELL 묶음(같은 orderId) = 최초 진입(봇)
    그 이후의 SELL           = 추가 진입(불타기)  ← 측정 대상
    BUY                     = 청산(부분/전체)
  체결 대응은 FIFO. 수수료는 체결별 실측.

짝차이 = 추가분 수익률 − 최초분 수익률 (증거금 기준 %, 레버리지 2배 반영).

Run: .venv/Scripts/python.exe scripts/pyramid_ledger.py [--days 120]
watchdog ONESHOT 등록 가능(하루 1회면 충분).
"""
import sys, os, csv, json, time, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
UTC = timezone.utc
KST = timezone(timedelta(hours=9))
LEV = 2.0
OUT = ROOT / "data" / "pyramid_ledger.csv"
SRC = [ROOT / "data" / "margin_short_trades.csv",
       ROOT / "data" / "margin_short_wide_trades.csv"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def user_trades(sym, s_ms, e_ms):
    from bithumb.binance_guard import _signed
    r = _signed("GET", "/fapi/v1/userTrades",
                params={"symbol": sym, "startTime": s_ms, "endTime": e_ms, "limit": 1000})
    d = r.json() if hasattr(r, "json") else json.loads(r)
    if isinstance(d, dict):          # 에러 응답
        return None
    return sorted(d, key=lambda x: (x["time"], x["id"]))


def split_tranches(fills):
    """반환: (최초분 리스트, 추가분 리스트, 청산분 리스트). 각 원소 = (qty, price, fee)."""
    sells = [f for f in fills if f["side"] == "SELL"]
    buys = [f for f in fills if f["side"] == "BUY"]
    if not sells:
        return [], [], []
    first_oid = sells[0]["orderId"]
    base = [(float(f["qty"]), float(f["price"]), float(f["commission"]))
            for f in sells if f["orderId"] == first_oid]
    add = [(float(f["qty"]), float(f["price"]), float(f["commission"]))
           for f in sells if f["orderId"] != first_oid]
    close = [(float(f["qty"]), float(f["price"]), float(f["commission"])) for f in buys]
    return base, add, close


def vwap(tr):
    q = sum(x[0] for x in tr)
    return (sum(x[0] * x[1] for x in tr) / q if q else 0.0), q, sum(x[2] for x in tr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    a = ap.parse_args()
    cutoff = datetime.now(UTC) - timedelta(days=a.days)

    rows = []
    for p in SRC:
        if not p.exists():
            continue
        for r in csv.DictReader(open(p, encoding="utf-8")):
            try:
                e = datetime.fromisoformat(r["entry_time"]).astimezone(UTC)
                x = datetime.fromisoformat(r["exit_time"]).astimezone(UTC)
            except Exception:
                continue
            if e < cutoff or not r.get("symbol"):
                continue
            rows.append((r["symbol"], e, x, float(r.get("margin_usdt") or 0), p.name))

    # ★ 2026-09-09 버그수정: 청산 시각에 +60초 여유를 주면 **같은 심볼의 다음 포지션
    #   진입 체결**이 이번 포지션의 "추가 진입"으로 잘못 잡힌다(손절 직후 재진입 시 발생).
    #   실제로 COTI/BICO/HEMI 3건이 이렇게 오분류됐다(추가가가 정확히 손절선 +40% 부근,
    #   추가가 == 청산가). 창의 끝을 **청산 시각 정각**으로 자르고, 추가로 같은 심볼의
    #   다음 진입 시각이 더 이르면 그쪽으로 더 당긴다.
    srt = sorted(rows, key=lambda z: z[1])
    nxt = {}
    for k, (sym_, e_, x_, _m, _s) in enumerate(srt):
        for j in range(k + 1, len(srt)):
            if srt[j][0] == sym_:
                nxt[k] = srt[j][1]
                break

    out = []
    for i, (sym, e, x, mg, src) in enumerate(srt):
        end = x
        if i in nxt and nxt[i] < end:
            end = nxt[i]
        f = user_trades(sym, int(e.timestamp() * 1000) - 60000,
                        int(end.timestamp() * 1000) - 1)
        time.sleep(0.12)
        if not f:
            continue
        base, add, close = split_tranches(f)
        if not base or not close:
            continue
        bpx, bq, bfee = vwap(base)
        cpx, cq, cfee = vwap(close)
        if bpx <= 0 or cpx <= 0:
            continue
        # 숏: 명목수익률 = (1 - 청산가/진입가)
        base_nom = (1 - cpx / bpx) * 100
        rec = dict(symbol=sym, entry_time=e.astimezone(KST).isoformat(),
                   exit_time=x.astimezone(KST).isoformat(), src=src,
                   base_qty=round(bq, 8), base_px=bpx, exit_px=cpx,
                   base_pct_margin=round(base_nom * LEV, 3),
                   n_add=len(add), add_qty=0.0, add_px=0.0,
                   add_pct_margin="", pair_diff_pp="",
                   add_kind="", add_vs_base_pct="")
        if add:
            apx, aq, afee = vwap(add)
            add_nom = (1 - cpx / apx) * 100
            # ★ 2026-09-09 추가: 숏 기준 추가 진입가가 최초가보다
            #   **낮으면 불타기**(이미 유리해진 뒤 얹음), **높으면 물타기**(불리해진 뒤 얹음).
            #   가격 비교만 쓰는 기계적 규칙이며 성적과 무관하다.
            #   ※ 이 구분은 사전등록(PREREG_PYRAMID.md) 작성 시 예상하지 못했고
            #     과거 6건을 본 뒤에 추가했다. would_change_log에 기록했다.
            rec.update(add_qty=round(aq, 8), add_px=apx,
                       add_pct_margin=round(add_nom * LEV, 3),
                       pair_diff_pp=round((add_nom - base_nom) * LEV, 3),
                       add_kind=("불타기" if apx < bpx else "물타기"),
                       add_vs_base_pct=round((apx / bpx - 1) * 100, 2))
        out.append(rec)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(rows)} 처리", flush=True)

    if not out:
        print("대상 없음"); return
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)

    withadd = [r for r in out if r["n_add"] > 0]
    print(f"\n포지션 {len(out)}건 중 **추가 진입(불타기) 있는 건 {len(withadd)}건**")
    print(f"기록: {OUT}")
    if withadd:
        import statistics as st
        d = [r["pair_diff_pp"] for r in withadd]
        print(f"\n짝차이(추가분 − 최초분) 평균 {st.mean(d):+.2f}%p  n={len(d)}")
        print(f"  추가분 평균 {st.mean([r['add_pct_margin'] for r in withadd]):+.2f}%  "
              f"최초분 평균 {st.mean([r['base_pct_margin'] for r in withadd]):+.2f}%")
        print(f"  ※ 사전등록 판정은 30건 또는 2026-12-31. 지금 수치는 판정이 아니다.")
        for r in withadd[-10:]:
            print(f"    {r['symbol']:12s} 최초 {r['base_pct_margin']:+7.2f}% / "
                  f"추가 {r['add_pct_margin']:+7.2f}%  짝차이 {r['pair_diff_pp']:+7.2f}%p")
    else:
        print("아직 추가 진입 기록이 없다. 불타기를 하시면 이 스크립트가 자동으로 잡는다.")


if __name__ == "__main__":
    main()
