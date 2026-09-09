"""
예측 vs 실제 대조표 (forecast_scorecard) — 2026-09-05 사용자 요청.
"백데이터로 뽑은 규칙이 앞에서도 맞고 있는가"를 매주 한 장으로 붙인다.

- 예측: data/forecast_baselines.json (고정값. 규칙이 사전등록으로 바뀔 때만 갱신)
- 실제: 거래소 원장(ledger_reconcile 산출) — 규칙 적용일(rule_since) 이후 진입 건만
- 판정(기록용, 행동 트리거 아님):
    표본 부족  n < 10
    일치       실거래 95% CI가 예측 점추정을 포함
    경계       CI가 예측을 벗어나지만 예측 CI와는 겹침
    괴리       실거래 CI와 예측 CI가 서로 안 겹침 → 시장이 바뀌었거나 백테스트 가정이 틀림. 규칙 재검토 후보(자동 변경 없음)
출력: docs/SCORECARD.md(append) + 텔레그램 요약. 읽기 전용, 주문 없음.
watchdog ONESHOT(7일 간격) 등록. 수동: .venv/Scripts/python.exe scripts/forecast_scorecard.py [--no-tg]
"""
import sys, json, argparse, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KST = timezone(timedelta(hours=9))
BASE_PATH = ROOT / "data" / "forecast_baselines.json"
OUT = ROOT / "docs" / "SCORECARD.md"
STAMP = ROOT / "data" / "_forecast_scorecard_last.txt"
MIN_GAP_SEC = 6 * 86400          # ★ 2026-09-06 B3: 워치독 재시작마다 메모리 카운터가 리셋돼
                                 #   7일 간격이 안 지켜졌다(실측 23시간). 파일 스탬프로 보강.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def boot_ci(x, B=4000, seed=20260905):
    rng = np.random.default_rng(seed); x = np.asarray(x, float)
    if len(x) < 2:
        return float("nan"), float("nan")
    m = np.array([rng.choice(x, len(x)).mean() for _ in range(B)])
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def verdict(n, mean, lo, hi, ev, ci):
    if n < 10:
        return "표본 부족"
    if lo <= ev <= hi:
        return "일치"
    if not (hi < ci[0] or lo > ci[1]):
        return "경계"
    return "괴리"


def engine_block(key, cfg):
    df = pd.read_csv(ROOT / cfg["ledger"])
    df = df[df.entry_time >= cfg["rule_since"]].copy()
    t = pd.to_datetime(df.exit_time, utc=True).dt.tz_convert("Asia/Seoul")
    df["week"] = (t - pd.to_timedelta(t.dt.weekday, unit="D")).dt.strftime("%m/%d~")
    n = len(df); x = df.net_pnl_pct_margin.values
    mean = float(x.mean()) if n else float("nan"); lo, hi = boot_ci(x)
    win = float((x > 0).mean() * 100) if n else float("nan")
    pred_usdt = float((df.margin_usdt * cfg["ev_pct_margin"] / 100).sum()) if n else 0.0
    act_usdt = float(df.net_pnl_usdt.sum()) if n else 0.0
    v = verdict(n, mean, lo, hi, cfg["ev_pct_margin"], cfg["ci95"])
    weekly = df.groupby("week").agg(n=("net_pnl_usdt", "count"), 건당=("net_pnl_pct_margin", "mean"), 순=("net_pnl_usdt", "sum")).round(2) if n else None
    return dict(key=key, n=n, mean=mean, lo=lo, hi=hi, win=win, pred_usdt=pred_usdt, act_usdt=act_usdt, verdict=v, weekly=weekly, cfg=cfg)


def btc_block():
    try:
        from bithumb.binance_guard import _signed
        p = [x for x in _signed("GET", "/fapi/v2/positionRisk").json() if x["symbol"] == "BTCUSDT"]
        if not p or float(p[0]["positionAmt"]) == 0:
            return "포지션 없음"
        p = p[0]
        return f"{float(p['positionAmt']):.3f} BTC | 평균 {float(p['entryPrice']):,.0f} → {float(p['markPrice']):,.0f} | 미실현 {float(p['unRealizedProfit']):+.1f} USDT"
    except Exception as e:
        return f"조회 실패 {e}"


def _too_soon() -> bool:
    try:
        return (time.time() - float(STAMP.read_text().strip())) < MIN_GAP_SEC
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--no-tg", action="store_true")
    ap.add_argument("--force", action="store_true", help="주기 제한 무시")
    a = ap.parse_args()
    if not a.force and _too_soon():
        print("최근에 이미 실행됨 — 생략(주 1회)"); return
    now = datetime.now(KST)
    try:
        BASE = json.loads(BASE_PATH.read_text(encoding="utf-8"))
        blocks = [engine_block(k, c) for k, c in BASE["engines"].items()]
    except Exception as e:
        # ★ 2026-09-06 B2: 여기서 예외로 죽으면 ONESHOT이 exit!=0 → 워치독이 최소간격을
        #   무시하고 40초마다 재기동한다(서명 API 반복 호출). 반드시 정상 종료한다.
        print(f"대조표 생성 실패: {type(e).__name__}: {e}")
        return
    lines = [f"## {now:%Y-%m-%d %H:%M} KST — 예측 vs 실제", "",
             "| 엔진 | 규칙 적용 | n | 예측 건당 | 실제 건당 (95% CI) | 승률 | 예측 누적 | 실제 누적 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|"]
    tg = [f"[예측대조] 📋 예측 vs 실제 ({now:%m/%d})"]   # ★ 2026-09-06 B1: 이 표식이 없으면 notify 화이트리스트에 막혀 조용히 안 감
    for b in blocks:
        c = b["cfg"]; ev = c["ev_pct_margin"]
        if b["n"]:
            lines.append(f"| {b['key']} | {c['rule_since']}~ | {b['n']} | {ev:+.2f}% [{c['ci95'][0]:+.1f},{c['ci95'][1]:+.1f}] | "
                         f"**{b['mean']:+.2f}%** [{b['lo']:+.1f},{b['hi']:+.1f}] | {b['win']:.0f}% | {b['pred_usdt']:+.0f} | **{b['act_usdt']:+.0f}** USDT | **{b['verdict']}** |")
            tg.append(f"{b['key']}: n={b['n']} 예측 {ev:+.1f}% / 실제 {b['mean']:+.1f}% [{b['lo']:+.1f},{b['hi']:+.1f}] → {b['verdict']} (누적 예측 {b['pred_usdt']:+.0f} vs 실제 {b['act_usdt']:+.0f})")
        else:
            lines.append(f"| {b['key']} | {c['rule_since']}~ | 0 | {ev:+.2f}% | — | — | — | — | 표본 없음 |")
            tg.append(f"{b['key']}: 규칙 적용 후 완결 거래 0건")
    lines += ["", f"BTC 추세봇(core_lev, 예측 열 없음): {btc_block()}", ""]
    for b in blocks:
        if b["weekly"] is not None and len(b["weekly"]):
            lines.append(f"**{b['key']} 주별** (청산 주 기준, 건당 증거금 기준 %)"); lines.append("")
            lines.append("| 주 | n | 건당 | 순 USDT |"); lines.append("|---|---|---|---|")
            for wk, r in b["weekly"].iterrows():
                lines.append(f"| {wk} | {int(r.n)} | {r.건당:+.2f}% | {r.순:+.1f} |")
            lines.append("")
    lines.append("판정 뜻: 일치=실거래 CI가 예측을 포함 / 경계=벗어나지만 두 CI가 겹침 / 괴리=두 CI가 안 겹침(시장 변화 또는 백테스트 가정 오류 → 규칙 재검토 후보, 자동 변경 없음). 예측값은 `data/forecast_baselines.json` 고정.")
    lines.append("")
    text = "\n".join(lines)
    print(text)
    # ★ 2026-09-06 B2: 파일이 편집기로 열려 있으면 PermissionError → ONESHOT 무한 재기동.
    #   이 프로젝트는 같은 사고를 log_trade에서 겪고 예외처리를 넣었다.
    try:
        if not OUT.exists():
            OUT.write_text("# SCORECARD — 백테스트 예측 vs 실거래 실제 (주간)\n\n예측은 규칙 사전등록 시점에 고정, 실제는 거래소 원장. 예측이 계속 맞으면 규칙이 살아 있는 것, 벌어지면 시장이 바뀐 신호.\n\n", encoding="utf-8")
        with OUT.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception as e:
        print(f"SCORECARD.md 기록 실패(파일이 열려 있는지 확인): {type(e).__name__}: {e}")
    if not a.no_tg:
        try:
            from bithumb import notify
            ok = notify.send("\n".join(tg))
            print("텔레그램 전송:", "성공" if ok else "실패/차단 — 화이트리스트·무음시간 확인")
        except Exception as e:
            print("텔레그램 전송 실패:", e)
    try:
        STAMP.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
