"""
실측 확률 조회기 (baserate) — 2026-09-10 사용자 요청.
"5분봉을 분석해서 퍼센테이지로 확률로 알려줘"

**예측기가 아니다. 조회기다.**
"지금 이 코인과 **같은 상태**였던 과거 사례들이 실제로 어떻게 됐는가"를
우리 1년치 5분봉(805종목, 2025-09~2026-07)에서 직접 세어서 보여준다.
새 모델도, 추정도 없다. 세는 것뿐이다.

## 무엇을 상태로 보는가 (지금 고정, 결과 보고 바꾸지 않는다)
현재 봉 기준 네 가지 — 전부 실시간 관측 가능하고, 백테스트에서 동일하게 계산된다.
  A 7시간 수익률   (현행 봇의 진입 기준과 같은 값)
  B 1시간 수익률   (직전 흐름)
  C 24시간 거래대금 (유동성)
  D 현재가가 24시간 고점 대비 몇 %  (고점 부근인가 되돌린 상태인가)

각 축에서 **가까운 구간**에 있던 과거 시점을 모아 그 뒤 결과를 센다.

## 무엇을 보고하는가
지평 4/12/24/48시간 각각에 대해:
  - **오를 확률 / 내릴 확률** (그냥 방향, 비용 미반영)
  - 평균·중앙값 (명목 %)
  - 표본 수와 **95% 신뢰구간**
  - **롱·숏 각각의 비용 반영 기대값** (수수료 왕복 0.10% 명목, 레버리지 2배 환산 병기)

## 반드시 같이 읽을 것
- 이건 **과거 빈도**이지 미래 확률이 아니다. 시장이 바뀌면 안 맞는다.
- 신뢰구간이 넓으면 "모른다"는 뜻이다. 승률 55%에 CI가 [45,65]면 동전과 구분 안 된다.
- ★ **이 표를 전략 판단에 쓰지 말 것**(2026-09-11 사고). 여기엔 쿨다운·손절 시뮬·펀딩·
  슬롯 제약이 **전부 빠져 있다.** 2026-09-11에 이 표로 "4시간 보유 +0.222%"를 보고했다가,
  봇과 동일 조건으로 재계산하니 **-1.19%로 부호가 뒤집혔다.**
  **용도는 오직 "지금 이 상태의 과거 빈도 조회" 하나다.** 보유·청산 규칙이 개입하는
  질문(얼마나 들고 있을까, 언제 자를까)에는 `research/m5bt/`의 정식 백테스트를 써야 한다.
- 이 저장소는 5개월간 37개 방향을 시험해 **예측력 있는 것을 하나도 못 찾았다.**
  이 도구도 예측력을 만들어내지 않는다. 실제 빈도를 보여줄 뿐이다.

Run: .venv/Scripts/python.exe scripts/baserate.py SYMBOL [SYMBOL2 ...]
     예) .venv/Scripts/python.exe scripts/baserate.py VTHOUSDT KATUSDT
"""
import sys, os, glob, argparse
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PQ = os.path.join(ROOT, "research", "m5bt", "pq")
BARS_1H, BARS_7H, BARS_24H = 12, 84, 288
# ★ 2026-09-16 사용자 요청: 15분·1시간 지평 추가. 짧은 지평은 수수료(왕복 0.10% 명목)
#   비중이 커서 기대값이 거의 남지 않는다 — 그 사실이 보이도록 같은 비용으로 계산한다.
HORIZONS = [(1, "5분"), (3, "15분"), (12, "1시간"), (48, "4시간"), (144, "12시간"),
            (288, "24시간"), (576, "48시간"), (864, "72시간"), (2016, "7일")]
FEE_NOM = 0.10
CACHE = os.path.join(ROOT, "data", "_baserate_cache.npz")
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def build():
    """전 종목 전 시점의 (상태, 미래수익률) 표를 만든다. 한 번 만들고 캐시."""
    if os.path.exists(CACHE):
        z = np.load(CACHE)
        return {k: z[k] for k in z.files}
    print("과거 표 만드는 중(최초 1회, 1~3분)...", flush=True)
    R = {k: [] for k in ("r7", "r1", "qv", "dh", "f1", "f3", "f12", "f48", "f144", "f288", "f576", "f864", "f2016")}
    files = sorted(glob.glob(os.path.join(PQ, "*.npz")))
    for i, p in enumerate(files):
        z = np.load(p); c = z["c"]; h = z["h"]; qv = z["qv"]
        n = len(c)
        if n < BARS_24H + 2016 + 10:
            continue
        cs = np.concatenate(([0.0], np.cumsum(qv)))
        step = 12                                   # 1시간 간격 표본(인접 중복 완화)
        idx = np.arange(BARS_24H, n - 2016, step)
        if not len(idx): continue
        r7 = (c[idx] / c[idx - BARS_7H] - 1) * 100
        r1 = (c[idx] / c[idx - BARS_1H] - 1) * 100
        v24 = cs[idx] - cs[idx - BARS_24H]
        hi24 = np.array([h[j - BARS_24H:j + 1].max() for j in idx])
        dh = (c[idx] / hi24 - 1) * 100
        ok = (v24 >= 1_000_000) & np.isfinite(r7) & np.isfinite(r1)
        R["r7"].append(r7[ok]); R["r1"].append(r1[ok])
        R["qv"].append(v24[ok]); R["dh"].append(dh[ok])
        for b, key in ((1, "f1"), (3, "f3"), (12, "f12"), (48, "f48"), (144, "f144"), (288, "f288"), (576, "f576"), (864, "f864"), (2016, "f2016")):
            R[key].append(((c[idx + b] / c[idx] - 1) * 100)[ok])
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(files)}", flush=True)
    out = {k: np.concatenate(v).astype(np.float32) for k, v in R.items()}
    np.savez_compressed(CACHE, **out)
    print(f"완료: 표본 {len(out['r7']):,}개")
    return out


def live_state(sym):
    import requests
    k = requests.get("https://fapi.binance.com/fapi/v1/klines",
                     params={"symbol": sym, "interval": "5m", "limit": 300}, timeout=25).json()
    if not isinstance(k, list) or len(k) < BARS_24H + 1:
        return None
    c = np.array([float(x[4]) for x in k]); h = np.array([float(x[2]) for x in k])
    qv = np.array([float(x[7]) for x in k])
    return dict(px=c[-1],
                r7=(c[-1] / c[-1 - BARS_7H] - 1) * 100,
                r1=(c[-1] / c[-1 - BARS_1H] - 1) * 100,
                qv=qv[-BARS_24H:].sum(),
                dh=(c[-1] / h[-BARS_24H:].max() - 1) * 100)


def ci_prop(k, n):
    if n == 0: return 0, 0
    p = k / n; se = (p * (1 - p) / n) ** 0.5
    return max(0, (p - 1.96 * se) * 100), min(100, (p + 1.96 * se) * 100)


def report(sym, T):
    s = live_state(sym)
    if s is None:
        print(f"\n[{sym}] 시세 조회 실패"); return
    print(f"\n{'='*74}")
    print(f"[{sym}]  현재 {s['px']:.8g}")
    print(f"  지금 상태 — 7시간 {s['r7']:+.1f}% / 1시간 {s['r1']:+.1f}% / "
          f"24h 거래대금 {s['qv']/1e4:.0f}만 / 24h고점 대비 {s['dh']:+.1f}%")
    # 가까운 구간: 각 축에서 상대 허용폭
    m = ((np.abs(T["r7"] - s["r7"]) <= max(3.0, abs(s["r7"]) * 0.25)) &
         (np.abs(T["r1"] - s["r1"]) <= max(1.5, abs(s["r1"]) * 0.35)) &
         (np.abs(T["dh"] - s["dh"]) <= 5.0) &
         (T["qv"] >= s["qv"] * 0.25) & (T["qv"] <= s["qv"] * 4.0))
    n = int(m.sum())
    print(f"  → 과거 같은 상태였던 시점 **{n:,}개** (805종목 1년, 1시간 간격 표본)")
    if n < 30:
        print("  ⚠ 표본 30개 미만 — 아무 말도 하지 않는다."); return
    print(f"\n  {'지평':>6s}{'오를확률':>10s}{'95%CI':>16s}{'평균':>9s}{'중앙':>9s}"
          f"{'롱기대':>10s}{'숏기대':>10s}")
    for b, lab in HORIZONS:
        f = T[{1: "f1", 3: "f3", 12: "f12", 48: "f48", 144: "f144", 288: "f288", 576: "f576", 864: "f864", 2016: "f2016"}[b]][m]
        up = int((f > 0).sum()); lo, hi = ci_prop(up, len(f))
        lng = f.mean() - FEE_NOM; sht = -f.mean() - FEE_NOM
        flat = "  ← 동전과 구분 불가" if (lo <= 50 <= hi) else ""
        print(f"  {lab:>6s}{up/len(f)*100:>9.1f}%{f'[{lo:.0f},{hi:.0f}]':>16s}"
              f"{f.mean():>+8.2f}%{np.median(f):>+8.2f}%{lng:>+9.2f}%{sht:>+9.2f}%{flat}")
    print("\n  ※ 롱/숏 기대 = 명목 기준, 수수료 왕복 0.10% 반영. 증거금 기준은 2배(레버 2배).")
    print("  ※ 이건 과거 빈도이지 미래 확률이 아니다. CI가 50%를 걸치면 판단 근거로 쓰지 말 것.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    a = ap.parse_args()
    T = build()
    print(f"\n조회 기반: 805종목 × 2025-09~2026-07, 표본 {len(T['r7']):,}개")
    for s in a.symbols:
        report(s.upper() if s.upper().endswith("USDT") else s.upper() + "USDT", T)


if __name__ == "__main__":
    main()
