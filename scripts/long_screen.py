"""
롱 후보 스크리너 — 2026-09-12 사용자 요청("기술지표로 롱처럼 보이는 리스트, 선택은 내가").

**추천이 아니다. 지표 계산 + 과거 실측 빈도 조회다.**
정렬은 지표가 아니라 **과거 승률**로 한다 — "좋아 보이는 순"이 아니라
"과거에 그 상태였던 것들이 실제로 오른 비율 순"이다.

## 반드시 같이 읽을 것
- 이 저장소는 **알트 롱을 8번 시험해 8번 다 기각**했다(알트 모멘텀 730건, 미러롱,
  손절후 롱전환 2회, 조용한급등 60쌍, CUSUM거울상, BTC하락매수, 급등지속롱, 저CUSUM롱).
- **LLM 에이전트가 직접 고르는 것도 164건 시험해 기각**됐다 —
  "항상 숏" +0.35% vs 에이전트 최고 +1.26%(CI 0 포함). 고르는 능력이 검출되지 않았다.
- 알트는 레짐 무관하게 1년 중앙값 **-50~-68%**다(1,171종목 실측).
- 따라서 이 목록은 **"덜 나쁜 것"의 목록이지 "좋은 것"의 목록이 아니다.**

Run: .venv/Scripts/python.exe scripts/long_screen.py [--top 15]
"""
import sys, os, time, argparse
import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "_baserate_cache.npz")
F = "https://fapi.binance.com"
MIN_QV = 3_000_000
B1H, B24 = 12, 288
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def rsi(c, n=14):
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    if len(up) < n: return 50.0
    au, ad = up[-n:].mean(), dn[-n:].mean()
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    if not os.path.exists(CACHE):
        print("실측 표가 없습니다. scripts/baserate.py 를 한 번 돌려주세요."); return
    z = np.load(CACHE)
    T = {k: z[k] for k in z.files}

    tick = requests.get(F + "/fapi/v1/ticker/24hr", timeout=30).json()
    cand = [d["symbol"] for d in tick
            if d["symbol"].endswith("USDT") and float(d["quoteVolume"]) >= MIN_QV
            and float(d["lastPrice"]) > 0]
    print(f"후보 {len(cand)}종목 스캔 중...", flush=True)
    out = []
    for i, s in enumerate(cand):
        try:
            k = requests.get(F + "/fapi/v1/klines",
                             params={"symbol": s, "interval": "5m", "limit": 300}, timeout=15).json()
            if len(k) < 290: continue
            c = np.array([float(x[4]) for x in k]); h = np.array([float(x[2]) for x in k])
            qv = np.array([float(x[7]) for x in k])
            cur = c[-1]
            r1 = (cur / c[-1 - B1H] - 1) * 100
            r7 = (cur / c[-85] - 1) * 100
            dh = (cur / h[-B24:].max() - 1) * 100
            v24 = qv[-B24:].sum()
            ma7 = c[-84:].mean(); ma24 = c[-B24:].mean()
            rs = rsi(c[-60:])
            # 과거 같은 상태 조회
            m = ((np.abs(T["r7"] - r7) <= max(3.0, abs(r7) * 0.25)) &
                 (np.abs(T["r1"] - r1) <= max(1.5, abs(r1) * 0.35)) &
                 (np.abs(T["dh"] - dh) <= 5.0) &
                 (T["qv"] >= v24 * 0.25) & (T["qv"] <= v24 * 4.0))
            n = int(m.sum())
            if n < 50: continue
            f = T["f288"][m]                      # 24시간 지평
            up = float((f > 0).mean() * 100)
            p = up / 100; se = (p * (1 - p) / n) ** 0.5 * 100
            out.append((s[:-4], up, up - 1.96 * se, r1, r7, dh, rs,
                        cur > ma7, cur > ma24, v24 / 1e4, n, float(np.median(f))))
        except Exception:
            pass
        time.sleep(0.02)
        if (i + 1) % 60 == 0: print(f"  {i+1}/{len(cand)}", flush=True)

    out.sort(key=lambda x: -x[1])
    print()
    print("=" * 96)
    print("  롱 후보 — **과거 24시간 상승 빈도 순** (지표 순 아님)")
    print("=" * 96)
    print(f"{'종목':<12}{'과거상승률':>10}{'95%CI하한':>10}{'1시간':>8}{'7시간':>8}"
          f"{'고점대비':>9}{'RSI':>6}{'MA':>6}{'표본':>7}{'중앙값':>9}")
    for r in out[:a.top]:
        s, up, lo, r1, r7, dh, rs, m7, m24, v, n, med = r
        ma = ('7' if m7 else '') + ('24' if m24 else '')
        mark = "  ★50%초과확정" if lo > 50 else ""
        print(f"{s:<12}{up:>9.1f}%{lo:>9.1f}%{r1:>+7.1f}%{r7:>+7.1f}%"
              f"{dh:>+8.1f}%{rs:>6.0f}{ma:>6}{n:>7}{med:>+8.2f}%{mark}")
    print()
    up50 = sum(1 for r in out if r[2] > 50)
    print(f"  전체 {len(out)}종목 중 95%CI 하한이 50%를 넘는 종목: **{up50}개**")
    print()
    print("  ※ '과거상승률' = 과거 같은 상태였던 시점들이 24시간 뒤 올랐던 비율.")
    print("  ※ CI 하한이 50% 아래면 **동전던지기와 구분 불가**다. 판단 근거로 쓰지 말 것.")
    print("  ※ 이 저장소는 알트 롱을 8번 시험해 8번 기각했다. 이건 '덜 나쁜 것' 목록이다.")


if __name__ == "__main__":
    main()
