"""PREREG_PYRAMID.md 3절 판정 기준 계산. pyramid_bt.py run의 결과(pyramid_result_notrail.pkl)를
읽어서 5개 채택기준 + 참고기록을 계산한다. 결과 보고 기준을 바꾸지 않는다(CLAUDE.md 7항)."""
import os, pickle, hashlib
import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
rows = pickle.load(open(os.path.join(D, "pyramid_result_notrail.pkl"), "rb"))
# row = (sym, ts, holdout, ret0_orig, ret1_orig, ret1_cap, added, kind)

syms = np.array([r[0] for r in rows])
holdout = np.array([r[2] for r in rows])
ret0 = np.array([r[3] for r in rows], dtype=np.float64)   # 기준(V0), 원자본 기준 %
added = np.array([r[6] for r in rows], dtype=bool)
ret1_cap = np.array([r[5] for r in rows], dtype=np.float64)  # 불타기 쪽 블렌드 평균수익률 %
total_qty = np.where(added, 1.5, 1.0)
ret1_orig_capital = ret1_cap / 100.0 * total_qty * 100.0    # 원자본 기준 % (증액분 포함 총손익 / 원자본)

diff = ret1_orig_capital - ret0   # 짝차이, 원자본 기준 %p

n = len(diff)
print(f"신호 수 n={n}, 불타기 발동={added.sum()}건 ({added.mean()*100:.1f}%)")
print()

# ── 기준1: 짝차이 평균 > 0 ──
m = diff.mean()
print(f"[기준1] 짝차이 평균 = {m:+.4f}%p (원자본 기준) → {'통과' if m>0 else '기각'}")

# ── 기준2: 부트스트랩 95% CI 하한 > 0 ──
rng_state = np.arange(n)
B = 4000
boot_means = np.empty(B)
# Date.now/random 계열 금지 규칙은 워크플로 스크립트에만 적용됨(여긴 일반 py) — 시드 고정으로 재현성 확보
rs = np.random.RandomState(20260830)
for b in range(B):
    idx = rs.randint(0, n, n)
    boot_means[b] = diff[idx].mean()
lo, hi = np.percentile(boot_means, [2.5, 97.5])
print(f"[기준2] 부트스트랩(B={B}) 95% CI = [{lo:+.4f}, {hi:+.4f}] → {'통과' if lo>0 else '기각'}")

# ── 기준3: 최대기여 단일 거래 제외 시 부호 유지 ──
biggest_idx = np.argmax(np.abs(diff))
diff_excl = np.delete(diff, biggest_idx)
m_excl = diff_excl.mean()
print(f"[기준3] 최대기여 1건 제외({syms[biggest_idx]}, 기여 {diff[biggest_idx]:+.2f}%p) "
      f"제외 후 평균 = {m_excl:+.4f}%p → {'통과(부호유지)' if (m_excl>0)==(m>0) else '기각(부호반전)'}")

# ── 기준4: 홀드아웃 부호 일치 ──
m_hold = diff[holdout].mean()
m_train = diff[~holdout].mean()
print(f"[기준4] 훈련({(~holdout).sum()}건) 평균={m_train:+.4f}%p / "
      f"홀드아웃({holdout.sum()}건) 평균={m_hold:+.4f}%p → "
      f"{'통과(부호일치)' if (m_hold>0)==(m_train>0) else '기각(부호불일치)'}")

# ── 기준5: 꼬리위험 — 불타기 최악10 vs 기준 최악10 ──
worst10_pyr = np.sort(ret1_orig_capital)[:10].mean()
worst10_base = np.sort(ret0)[:10].mean()
tail_ok = worst10_pyr >= worst10_base
print(f"[기준5-필수] 최악10건 평균 — 기준={worst10_base:+.4f}%  불타기={worst10_pyr:+.4f}% "
      f"→ {'통과(더 나쁘지 않음)' if tail_ok else '기각(꼬리 악화)'}")

print()
all_pass = (m>0) and (lo>0) and ((m_excl>0)==(m>0)) and ((m_hold>0)==(m_train>0)) and tail_ok
print(f"=== 최종: {'채택 (5개 기준 전부 통과)' if all_pass else '기각 (1개 이상 미충족)'} ===")
print()

# ── 참고기록(판정 아님) ──
win_added = (ret1_orig_capital[added] > ret0[added]).mean() if added.sum() else float('nan')
win_notadded = (ret1_orig_capital[~added] > ret0[~added]).mean() if (~added).sum() else float('nan')
print(f"[참고] 발동 시 불타기가 기준보다 나은 비율 = {win_added*100:.1f}% ({added.sum()}건)")
print(f"[참고] 미발동 시(동일신호, add_trig 미도달) 짝차이 = "
      f"{diff[~added].mean():+.4f}%p (이 경우 이론상 0이어야 함 — 검증용)")
kinds = [r[7] for r in rows]
from collections import Counter
print(f"[참고] 불타기쪽 청산유형 분포: {Counter(kinds)}")
print(f"[참고] 발동 후 청산유형 분포(발동={added.sum()}건 중): "
      f"{Counter(k for k,a in zip(kinds, added) if a)}")
