"""
그림자함대 V8_halftrim(절반청산) 판정 계산기 — docs/PREREG_HALFTRIM.md 5·6절 그대로.

작성 2026-10-13. 문서의 기준(Z1~Z6)을 한 글자도 바꾸지 않고 옮겼다.
출력을 그대로 판정문에 붙인다. 숫자를 손으로 옮기지 않는다.

기준(문서 6절):
  Z1 짝차이(V8−V1) 평균 — 병기만(판정에 안 씀)
  Z2 V8 최악 10건 평균 손실이 V1 최악 10건 평균 손실보다 50% 이상 덜 나빠야 채택
  Z3 Z2가 부호까지 뒤집혀 V8이 더 나쁘면 즉시 기각
  Z4 절반청산 발동 비율 — 보고
  Z5 발동 안 한 신호(leg=full)에서 V8 = V1 정확히 일치(회귀 관문, 필수)
  Z6 봉인: md5(sym)%4==0 홀드아웃에서 Z2 방향 동일 — 참고

잣대: 신호별 net_pnl_usdt 합(트림+최종 레그) ÷ MARGIN_USDT(30, 트림 전 전체 증거금) × 100
      = 증거금 기준 %(펀딩·수수료 포함). 레그별 net_pnl_pct_margin은 직접 합산하지 않는다(문서 3절).
범위: 원본봇 신호셋(PUMP 30~40%)이다. 완화봇(mshort_wide_fut)에는 자동 적용되지 않는다(문서 4절).

Run: .venv/Scripts/python.exe scripts/halftrim_eval.py
"""
import hashlib
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "shadow_trades.csv"
BASE, CAND = "V1_notrail", "V8_halftrim"
MARGIN_USDT = 30.0
SEED, B = 20261015, 4000
EPS = 0.005
WORST_K = 10

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def block_boot(vals, blocks, rng):
    keys = np.unique(blocks)
    groups = {k: vals[blocks == k] for k in keys}
    out = np.empty(B)
    for i in range(B):
        pick = rng.choice(keys, len(keys), replace=True)
        out[i] = np.concatenate([groups[k] for k in pick]).mean()
    return np.percentile(out, 2.5), np.percentile(out, 97.5)


def worst_mean(x, k=WORST_K):
    k = min(k, len(x))
    return np.sort(x)[:k].mean()


def main():
    df = pd.read_csv(CSV)
    df["leg"] = df["leg"].fillna("full")      # leg 열이 생기기 전 행은 전부 단일 청산
    df["day"] = pd.to_datetime(df["entry_time"], utc=True).dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d")

    v1 = df[df["variant"] == BASE]
    v8 = df[df["variant"] == CAND]

    # V8 완결 신호 = leg가 full 이거나 final 행이 있는 것(trim만 있으면 아직 열려 있음)
    done8 = set(v8.loc[v8["leg"].isin(["full", "final"]), "signal_id"])
    done1 = set(v1["signal_id"])
    ids = sorted(done8 & done1)

    g8 = v8[v8["signal_id"].isin(ids)].groupby("signal_id")
    g1 = v1[v1["signal_id"].isin(ids)].groupby("signal_id")
    r8 = g8["net_pnl_usdt"].sum() / MARGIN_USDT * 100
    r1 = g1["net_pnl_usdt"].sum() / MARGIN_USDT * 100
    trimmed = g8["leg"].apply(lambda s: (s == "trim").any())
    sym = g1["symbol"].first()
    day = g1["day"].first()

    w = pd.DataFrame({"v1": r1, "v8": r8, "trim": trimmed, "sym": sym, "day": day}).loc[ids]
    n = len(w)
    print("=" * 68)
    print("그림자함대 V8_halftrim 판정 계산기  (PREREG_HALFTRIM.md)  잣대=증거금 기준 %(펀딩·수수료 포함)")
    print(f"V8 완결 {len(done8)}건 / V1 완결 {len(done1)}건 / 짝 {n}쌍 "
          f"/ 기간 {w['day'].min()} ~ {w['day'].max()}" if n else "짝 0쌍")
    print("=" * 68)
    if n == 0:
        print("표본 없음 → 판정 불가")
        return

    d = (w["v8"] - w["v1"]).values
    blocks = w["day"].values
    rng = np.random.default_rng(SEED)
    lo, hi = block_boot(d, blocks, rng)

    # Z5 회귀 관문 — 절반청산이 발동하지 않은 신호는 V1과 정확히 같아야 한다
    nt = w[~w["trim"]]
    maxdiff = float((nt["v8"] - nt["v1"]).abs().max()) if len(nt) else float("nan")
    z5 = len(nt) > 0 and maxdiff < EPS

    # Z2/Z3 — 꼬리(최악 10건)
    wk = min(WORST_K, n)
    wv1, wv8 = worst_mean(w["v1"].values), worst_mean(w["v8"].values)
    # 손실 크기(음수의 절댓값)로 비교: 줄어든 비율 = 1 - |V8|/|V1|
    cut = 1 - (abs(wv8) / abs(wv1)) if wv1 < 0 else float("nan")
    z2 = cut == cut and cut >= 0.5
    z3 = wv8 < wv1          # V8이 더 나쁘면(더 큰 손실) 즉시 기각

    # Z4 발동 비율
    z4 = w["trim"].mean()

    # Z6 홀드아웃 md5(sym)%4==0
    hold = w[w["sym"].map(lambda s: int(hashlib.md5(str(s).encode()).hexdigest(), 16) % 4 == 0)]
    if len(hold) >= 3:
        h1, h8 = worst_mean(hold["v1"].values, min(WORST_K, len(hold))), worst_mean(hold["v8"].values, min(WORST_K, len(hold)))
        z6 = f"홀드아웃 {len(hold)}건 최악 평균 V1 {h1:+.1f} / V8 {h8:+.1f} → 방향 {'일치(V8이 덜 나쁨)' if h8 >= h1 else '불일치(V8이 더 나쁨)'}"
    else:
        z6 = f"홀드아웃 {len(hold)}건 — 표본 적어 생략"

    print(f"\n[기술] V1 평균 {w['v1'].mean():+.2f}%  중앙 {w['v1'].median():+.2f}%  최대손실 {w['v1'].min():+.1f}%")
    print(f"       V8 평균 {w['v8'].mean():+.2f}%  중앙 {w['v8'].median():+.2f}%  최대손실 {w['v8'].min():+.1f}%")
    print(f"\n  Z1 짝차이 평균(병기)      {d.mean():+.2f}%p   일블록 95% CI [{lo:+.2f}, {hi:+.2f}]  (판정에 안 씀)")
    print(f"  Z2 최악{wk}건 평균        V1 {wv1:+.2f}%  vs  V8 {wv8:+.2f}%  → 손실 {cut*100:+.1f}% 감소  "
          f"→ {'충족(≥50%)' if z2 else '미충족'}")
    print(f"  Z3 V8이 더 나쁜가         {'예 → 즉시 기각' if z3 else '아니오'}")
    print(f"  Z4 절반청산 발동 비율     {z4*100:.1f}% ({int(w['trim'].sum())}/{n})")
    print(f"  Z5 회귀관문(미발동 {len(nt)}건) 최대 어긋남 {maxdiff:.4f}%p → {'통과' if z5 else '**실패 → 전체 폐기**'}")
    print(f"  Z6 {z6}")

    if not z5:
        verdict = "회귀 관문 실패 → 절반청산 로직 버그, 전체 폐기"
    elif z3:
        verdict = "기각 (Z3: V8이 V1보다 꼬리가 더 나쁨)"
    elif z2:
        verdict = "**채택 후보** — 단 원본봇 신호셋 한정, 완화봇 적용은 별도 검증 후 사용자 결정(문서 4·7절)"
    else:
        verdict = "기각 (Z2 미충족: 꼬리 손실이 50% 이상 줄지 않음)"
    print(f"\n  → 판정: {verdict}")
    if n < 50:
        print(f"  ※ 완결 신호 {n}건 < 50 — 문서 5절: 2026-10-15 판정일에 그 시점 데이터로 판정(표본 부족 기록)")


if __name__ == "__main__":
    main()
