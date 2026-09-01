"""[알림] 보유 포지션 현황을 텔레그램으로 전송 — show_positions.py와 동일 포맷.
1시간마다 작업 스케줄러(CoinbaseTelegramStatus)로 실행."""
import sys, csv, json, time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bithumb import notify
from bithumb.binance_guard import _signed


def price(sym):
    """현물 가격, 없으면 선물 폴백. ★ 2026-09-01: 선물 전용 코인(SKR 등 347개)이
    유니버스에 들어오면서 현물 조회가 -1121로 실패('price' 키 없음) → /상태 전체가
    죽었다. 선물 티커로 폴백."""
    r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": sym}, timeout=5)
    d = r.json()
    if "price" in d:
        return float(d["price"])
    return _futures_price(sym)


def _futures_price(sym):
    r = requests.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": sym}, timeout=5)
    return float(r.json()["price"])


def _fees(sym, entry_ts):
    """진입 이후 누적 펀딩비+수수료(거래소 원장 실제값). 실패해도 표시만 저해되고
    봇 동작엔 영향 없음 — (0,0)으로 대체."""
    try:
        r = _signed("GET", "/fapi/v1/income",
                    {"symbol": sym, "startTime": int(entry_ts * 1000) - 60_000, "limit": 1000})
        rows = r.json()
        funding = sum(float(x["income"]) for x in rows if x["incomeType"] == "FUNDING_FEE")
        comm = sum(float(x["income"]) for x in rows if x["incomeType"] == "COMMISSION")
        return funding, comm
    except Exception:
        return 0.0, 0.0


def _remain_h(exit_ts):
    """exit_ts(만기 unix timestamp)가 있으면 "N.Nh", 없으면(재량매매 등 만기개념 없음) "-"."""
    if not exit_ts:
        return "-"
    h = (exit_ts - time.time()) / 3600
    return f"{h:.1f}h" if h >= 0 else "만기지남"


SHADOW_TARGET_N = 20  # DEADLINES.md 9/2 판정 최소표본 기준(변형당) — 남은건수 계산용


def _shadow_summary():
    """그림자 함대(shadow_fleet) 진행상황 — 2026-08-19 추가, 같은날 종목중심으로 개편.
    오픈 포지션은 실거래 포지션현황과 같은 포맷(종목/수익률/경과)으로 보여주고,
    변형마다 다르게 보유한 경우만 "제외" 줄에 표시. 순수모의라 가격 기준 미실현
    수익률만 보여줌(펀딩비 미반영) — 정밀 판정은 DEADLINES.md 마감일에 따로 함."""
    pos_path = ROOT / "data" / "shadow_fleet_pos.json"
    if not pos_path.exists():
        return None
    try:
        pos = json.loads(pos_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    sig_path = ROOT / "data" / "shadow_signals.csv"
    n_sig = 0
    if sig_path.exists():
        with open(sig_path, encoding="utf-8") as f:
            n_sig = max(sum(1 for _ in f) - 1, 0)  # 헤더 제외

    trades_path = ROOT / "data" / "shadow_trades.csv"
    n_trade = {}
    if trades_path.exists():
        with open(trades_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                n_trade[r["variant"]] = n_trade.get(r["variant"], 0) + 1

    all_variants = list(pos.keys())
    by_sym = {}
    for v, holdings in pos.items():
        for sym, p in holdings.items():
            d = by_sym.setdefault(sym, {"entry": p["entry_price"], "ts": p["entry_ts"], "variants": []})
            d["variants"].append(v)

    lines = ["", f"[그림자함대] 신호누적 {n_sig}건 (전종목 숏)"]
    if by_sym:
        lines.append("<pre>")
        # ★ 2026-08-29: 잣대 명시(CLAUDE.md 2항). 이 값은 **명목가 기준**인데 바로 위
        #   실거래 표는 명목·증거금을 함께 보여주므로, 라벨이 없으면 같은 기준으로 오독된다.
        #   증거금 기준은 이 값의 2배다(레버리지 2배).
        lines.append(f"{'종목':<8}{'명목':>8}{'경과':>7}")
        for sym, d in sorted(by_sym.items()):
            try:
                cur = _futures_price(sym)
                pnl_s = f"{(1 - cur / d['entry']) * 100:>+7.2f}%"
            except Exception:
                pnl_s = "      -"
            elapsed_h = (time.time() - d["ts"]) / 3600
            lines.append(f"{sym[:-4]:<8}{pnl_s}{elapsed_h:>6.1f}h")
            excluded = [v.split("_")[0] for v in all_variants if v not in d["variants"]]
            if excluded:
                lines.append(f" ㄴ제외:{','.join(excluded)}")
        lines.append("</pre>")
        lines.append("명목 기준(증거금 기준은 2배) · 모의라 펀딩비 미반영")
    else:
        lines.append("오픈 포지션 없음")

    prog = " ".join(
        f"{v.split('_')[0]} {n_trade.get(v, 0)}/{SHADOW_TARGET_N}(잔여{max(SHADOW_TARGET_N - n_trade.get(v, 0), 0)})"
        for v in all_variants)
    lines.append(f"청산누적(9/2목표): {prog}")
    return "\n".join(lines)


def build_text():
    rows = []

    # ★ 2026-08-25(버그헌터 발견, 즉시수정): 완화판 봇(margin_short_wide_trader)의 포지션
    #   파일을 안 읽어서, 실거래 포지션이 열려 있는데도 "보유 포지션 없음"으로 오보하고 있었다.
    #   [포지션현황]은 화이트리스트를 통과하는 몇 안 되는 알림이고 tg_bot 시작 멘트로도 쓰여
    #   사용자가 포지션을 인지하는 주 경로다. 어느 봇 것인지 구분해서 보여준다.
    for fname, tag in (("margin_short_pos.json", "숏"),
                       ("margin_short_wide_pos.json", "숏(완화)")):
        ms = ROOT / "data" / fname
        if not ms.exists():
            continue
        for sym, p in json.loads(ms.read_text(encoding="utf-8")).items():
            cur = price(sym)
            pnl_pct = (1 - cur / p["entry_price"]) * 100
            pnl_usdt = p["margin"] * 2 * (pnl_pct / 100)
            funding, comm = _fees(sym, p["entry_ts"])
            net_usdt = pnl_usdt + funding + comm
            rows.append((p["coin"], tag, pnl_pct, net_usdt, _remain_h(p.get("exit_ts"))))

    ml = ROOT / "data" / "margin_manual_long_pos.json"
    if ml.exists():
        for coin, p in json.loads(ml.read_text(encoding="utf-8")).items():
            cur = price(coin + "USDT")
            pnl_pct = (cur / p["entry_price"] - 1) * 100
            pnl_usdt = p["qty"] * (cur - p["entry_price"])
            rows.append((coin, "롱", pnl_pct, pnl_usdt, _remain_h(p.get("exit_ts"))))

    shadow = _shadow_summary()

    if not rows:
        text = "[포지션현황] 보유 포지션 없음"
        return text + (shadow or "")

    # ★ 2026-08-29(사용자 발견 "합계가 안 맞는데"): 합계 산수는 맞았으나 **수익률과 순익의
    #   잣대가 달라** 안 맞아 보였다. 수익률은 명목가 기준인데 순익은 margin×2×수익률이라
    #   (레버리지 2배) 증거금 대비로는 두 배로 보인다 — 증거금 30에 +19.6%인데 순익 +11.74.
    #   CLAUDE.md 2항("숫자를 인용할 때 반드시 잣대를 같이 적는다")을 이 화면이 안 지키고
    #   있었다. 명목·증거금 둘 다 표시해 오독을 원천 차단한다.
    lines = ["[포지션현황]", "<pre>"]
    lines.append(f"{'종목':<7}{'방향':<4}{'명목':>7}{'증거금':>8}{'순익':>9}  {'만기'}")
    total = 0.0
    for coin, direction, pct, usdt, remain in rows:
        lines.append(f"{coin:<7}{direction:<4}{pct:>+6.1f}%{pct*2:>+7.1f}%{usdt:>+9.2f}  {remain}")
        total += usdt
    lines.append(f"{'합계':<24}{total:>+9.2f}")
    lines.append("</pre>")
    lines.append("명목=가격 변동률 / 증거금=레버리지 2배 반영(순익은 이 기준)")
    lines.append("※ BTC 롱(core_lev)은 별도 엔진이라 이 표에 없습니다")
    return "\n".join(lines) + (shadow or "")


def main():
    text = build_text()
    notify.send(text, force=True)
    print(text)


if __name__ == "__main__":
    main()
