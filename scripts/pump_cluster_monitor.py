"""
급등 쏠림 감시기 (pump_cluster_monitor) — 2026-09-08 사용자 요청.

**읽기 전용. 주문·설정 변경 없음. 봇 로직도 건드리지 않는다. 알림만 보낸다.**

배경(2026-09-08 실측, `research/m5bt/`):
평소 급등 신호는 하루 2건(중앙값)인데, 2025-10-10 하루에 **415건**이 터졌다.
그날 숏 승률이 11%(평소 57%)였고, **1년 백테스트 손실의 90%가 그 하루에서 나왔다.**

| 하루 신호 수 | n | 평균(증거금 기준) | 승률 |
|---|---|---|---|
| 1~3건 | 386 | +0.30% | 56.7% |
| 4~9건 | 284 | -9.42% | 51.4% |
| 10~29건 | 11 | +11.99% | 72.7% |
| **30건 이상** | **415** | **-54.13%** | **10.6%** |

해석: 코인 하나가 혼자 튀면 되돌아오지만, **시장 전체가 한꺼번에 튀면 안 돌아온다.**
그건 개별 종목의 평균회귀가 아니라 시장 사건이다.

★ 이것은 **사후에 만든 관찰**이며 아직 필터로 검정되지 않았다. 그래서 이 스크립트는
  **알림만** 한다. 숏을 자동 중단시키지 않는다. 검정을 통과하기 전에는 봇에 넣지 않는다.

Run(수동): .venv/Scripts/python.exe scripts/pump_cluster_monitor.py [--print-only]
watchdog ONESHOT 등록(30분 간격).
"""
import sys, os, json, time, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
KST = timezone(timedelta(hours=9))
FAPI = "https://fapi.binance.com"

# 완화봇/원본봇과 동일한 신호 정의 (margin_short_wide_trader.py 기준)
LOOKBACK_H = 7
PUMP_LO = 15.0            # 두 봇을 합친 하한(완화 15, 원본 30)
MIN_QUOTE_VOL = 3_000_000
PRESCREEN_24H = 5.0

# 경보 구간 — 2026-09-08 실측 표에서 그대로 가져왔다(임의 조정 금지)
WARN_N = 10               # 10건 이상: 주의
DANGER_N = 30             # 30건 이상: 그날 승률 10.6% 구간

STATE = ROOT / "data" / "_pump_cluster_state.json"
OUT = ROOT / "data" / "pump_cluster_log.csv"
MIN_GAP_SEC = 3000        # 같은 등급 재알림 최소 간격(50분)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _get(path, params=None, timeout=20):
    import requests
    r = requests.get(FAPI + path, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def count_signals():
    """지금 이 순간 급등 조건을 만족하는 종목 수. (건수, 목록)"""
    tick = {}
    for d in _get("/fapi/v1/ticker/24hr"):
        s = d["symbol"]
        if not s.endswith("USDT"):
            continue
        tick[s] = (float(d["lastPrice"]), float(d["priceChangePercent"]), float(d["quoteVolume"]))
    cands = [s for s, (px, chg, qv) in tick.items()
             if px > 0 and qv >= MIN_QUOTE_VOL and chg >= PRESCREEN_24H]
    hits = []
    for s in cands:
        try:
            k = _get("/fapi/v1/klines", {"symbol": s, "interval": "5m", "limit": LOOKBACK_H * 12 + 1})
        except Exception:
            continue
        if len(k) < LOOKBACK_H * 12 + 1:
            continue
        ret = (float(k[-1][4]) / float(k[0][4]) - 1) * 100
        if ret >= PUMP_LO:
            hits.append((s[:-4], round(ret, 1)))
        time.sleep(0.03)
    hits.sort(key=lambda x: -x[1])
    return len(hits), hits


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--print-only", action="store_true")
    ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    now = datetime.now(KST)
    n, hits = count_signals()

    if n >= DANGER_N:
        level, head = "위험", f"🚨 급등 쏠림 위험 — 지금 {n}종목 동시 급등"
    elif n >= WARN_N:
        level, head = "주의", f"⚠️ 급등 쏠림 주의 — 지금 {n}종목 동시 급등"
    else:
        level, head = "정상", f"급등 쏠림 정상 — {n}종목"

    top = ", ".join(f"{c} +{r:.0f}%" for c, r in hits[:12])
    body = "\n".join([
        head,
        f"({now:%m/%d %H:%M} 기준, 7시간 +15% 이상 · 거래대금 300만 USDT 이상)",
        "",
        f"평소 하루 2건 수준입니다. 지금 {n}건입니다." if n >= WARN_N else f"평소 수준입니다(하루 2건 안팎).",
        "",
        f"종목: {top}" if top else "해당 종목 없음",
    ])
    if n >= DANGER_N:
        body += ("\n\n과거 이런 날(하루 30건 이상) 숏 승률은 10.6%였습니다(평소 57%).\n"
                 "시장 전체가 함께 움직이는 중일 수 있습니다.\n"
                 "※ 봇은 계속 규칙대로 돕니다. 이 알림은 판단 참고용이며 자동 중단은 하지 않습니다.")
    elif n >= WARN_N:
        body += "\n\n※ 알림만 보냅니다. 봇 동작은 그대로입니다."

    print(body)

    try:
        OUT.parent.mkdir(exist_ok=True)
        new = not OUT.exists()
        with OUT.open("a", encoding="utf-8") as f:
            if new:
                f.write("time,n_signals,level,top\n")
            f.write(f"{now.isoformat()},{n},{level},\"{top}\"\n")
    except Exception as e:
        print("기록 실패:", e)

    if a.print_only or level == "정상":
        return
    st = {}
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    if not a.force and time.time() - float(st.get(level, 0)) < MIN_GAP_SEC:
        print("최근에 같은 등급 알림을 보냄 — 생략"); return
    try:
        from bithumb import notify
        ok = notify.send(body)
        print("텔레그램:", "성공" if ok else "실패/차단")
        if ok:
            st[level] = time.time()
            tmp = STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(st), encoding="utf-8")
            os.replace(tmp, STATE)
    except Exception as e:
        print("텔레그램 전송 실패:", e)


if __name__ == "__main__":
    main()
