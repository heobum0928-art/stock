"""
그림자함대 V6_timestop · V7_fundexit 판정 계산기 — docs/PREREG_FLEET_V6V7.md 2절 그대로.

작성 2026-09-04 (결과 보기 전). 판정일 2026-09-19. **판정 전 수정 금지.**
출력을 그대로 판정문에 붙인다. 숫자를 손으로 옮기지 않는다.

기준(문서 2절):
  C1 짝차이(후보−V1) 평균 > 0
  C2 일-블록 부트스트랩 4000회(시드 20260919) 97.5% CI 하한 > 0  (후보 2개 본페로니)
  C3 최대기여 단일 쌍 제외 시 부호 유지(> 0)
  C4 발동한 쌍(diff≠0)만 봤을 때 후보 승률 > 50%
  C5 발동한 쌍에서 후보의 최악 5건 평균 ≥ V1의 최악 5건 평균
  + 단일사건 의존: 발동 쌍 짝차이 합에서 가장 큰 하루의 비율 > 50%면 통과해도 '보류'
  + 표본 미달: 발동 쌍 < 15면 '보류'(연장 2026-10-03 단 1회)

Run: .venv/Scripts/python.exe scripts/fleet_v6v7_eval.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "shadow_trades.csv"
BASE = "V1_notrail"
CANDS = ["V6_timestop", "V7_fundexit"]
METRIC = "net_pnl_pct_margin"
SEED, B = 20260919, 4000
CI_LO, CI_HI = 1.25, 98.75          # 97.5% CI (본페로니 2)
MIN_FIRED = 15
EPS = 0.005

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
    return np.percentile(out, CI_LO), np.percentile(out, CI_HI)


def main():
    df = pd.read_csv(CSV)
    df["day"] = pd.to_datetime(df["entry_time"], utc=True).dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d")
    w = df.pivot_table(index="signal_id", columns="variant", values=METRIC)
    day = df.drop_duplicates("signal_id").set_index("signal_id")["day"]
    print("=" * 68)
    print(f"그림자함대 V6/V7 판정 계산기  (PREREG_FLEET_V6V7.md)  잣대={METRIC} (증거금 기준, 펀딩·수수료 포함)")
    print(f"기준선 {BASE}: 청산 {int(w[BASE].notna().sum())}건")
    print("=" * 68)
    for c in CANDS:
        if c not in w.columns:
            print(f"\n[{c}] 기록 없음 → 표본 미달(0쌍) → 보류")
            continue
        pair = w[[BASE, c]].dropna()
        d = (pair[c] - pair[BASE]).values
        blocks = day.loc[pair.index].values
        n = len(d)
        fired = np.abs(d) > EPS
        nf = int(fired.sum())
        print(f"\n[{c}] 짝 {n}쌍 / 규칙 발동(diff≠0) {nf}쌍")
        if n == 0:
            print("  → 표본 미달 → 보류")
            continue
        rng = np.random.default_rng(SEED)
        mean = d.mean()
        lo, hi = block_boot(d, blocks, rng)
        c1 = mean > 0
        c2 = lo > 0
        d_drop = np.delete(d, int(np.argmax(d)))
        c3 = d_drop.mean() > 0 if len(d_drop) else False
        if nf:
            fd = d[fired]
            win = (fd > 0).mean()
            c4 = win > 0.5
            cand_f = pair[c].values[fired]
            base_f = pair[BASE].values[fired]
            k = min(5, nf)
            worst_c = np.sort(cand_f)[:k].mean()
            worst_b = np.sort(base_f)[:k].mean()
            c5 = worst_c >= worst_b
            fb = blocks[fired]
            tot = fd.sum()
            day_sum = pd.Series(fd).groupby(fb).sum()
            share = (day_sum.max() / tot) if tot > 0 else float("nan")
        else:
            win = float("nan"); c4 = False; worst_c = worst_b = float("nan"); c5 = False; share = float("nan")
        print(f"  C1 짝차이 평균           {mean:+.2f}%p                → {'충족' if c1 else '미충족'}")
        print(f"  C2 97.5% CI 하한(일블록) [{lo:+.2f}, {hi:+.2f}]        → {'충족' if c2 else '미충족'}")
        print(f"  C3 최대기여 1쌍 제외 평균 {d_drop.mean() if len(d_drop) else float('nan'):+.2f}%p                → {'충족' if c3 else '미충족'}")
        print(f"  C4 발동 쌍 승률          {win*100 if nf else float('nan'):.1f}% (n={nf})          → {'충족' if c4 else '미충족'}")
        print(f"  C5 발동 쌍 최악{min(5,nf) if nf else 0}건 평균  후보 {worst_c:+.1f} vs V1 {worst_b:+.1f}   → {'충족' if c5 else '미충족'}")
        print(f"  단일사건 의존: 최대 하루 비율 {share*100 if share==share else float('nan'):.0f}%  → {'경고(보류 사유)' if share==share and share>0.5 else '통과'}")
        allc = c1 and c2 and c3 and c4 and c5
        if nf < MIN_FIRED:
            verdict = f"표본 미달({nf}<{MIN_FIRED}) → 보류 (방향 {'+' if mean>0 else '-'}, 연장 2026-10-03 1회)"
        elif allc and share == share and share > 0.5:
            verdict = "C1~C5 통과했으나 단일사건 의존 → 보류"
        elif allc:
            verdict = "**채택 후보** (실거래 반영은 사용자 결정)"
        else:
            verdict = "기각·종료"
        print(f"  → 판정: {verdict}")
        # 보조 기록(판정 근거 아님)
        print(f"  (참고) 중앙값차 {np.median(d):+.2f}%p · 후보 단독 평균 {pair[c].mean():+.2f}% · V1 단독 평균 {pair[BASE].mean():+.2f}%")
    print("\n" + "=" * 68)
    print("이 출력을 그대로 판정문에 붙이십시오. 숫자를 손으로 옮겨적지 마십시오.")


if __name__ == "__main__":
    main()
