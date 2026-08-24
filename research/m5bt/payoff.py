"""서술적 요약: payoff 모양. 새 가설 검정 아님 — 기존 결과 기술."""
import numpy as np
from scipy import stats
def L(t):
    z=np.load('base_%s.npz'%t,allow_pickle=True); return z['ret_opt']*100, z['kind'], z['mfe'].astype(float), z['mae'].astype(float)
for nm,t in (("신호진입",'real'),("무작위진입",'rand')):
    r,k,mfe,mae=L(t); w=r>0
    print(f"=== {nm} n={len(r)} (증거금 기준 %) ===")
    print(f"  승률 {w.mean()*100:5.1f}%   평균승 {r[w].mean():+7.2f}   평균패 {r[~w].mean():+8.2f}")
    print(f"  기대값 {r.mean():+6.2f}   중앙값 {np.median(r):+6.2f}   왜도 {stats.skew(r):+6.2f}")
    q=np.percentile(r,[1,5,25,50,75,95,99])
    print("  분위 1/5/25/50/75/95/99: "+" ".join(f"{x:+7.1f}" for x in q))
    # 손실 집중도
    loss=np.sort(r[r<0]); tot=loss.sum()
    for p in (5,10,20):
        n=int(len(r)*p/100)
        print(f"  최악 {p:2d}% ({n:4d}건)이 전체 손실합의 {loss[:n].sum()/tot*100:5.1f}% / 총수익합 대비 {loss[:n].sum():+9.1f}%p")
    print()
r,_,_,_=L('real')
print("=== 만약 최악 상위 N건이 없었다면 (사후가정, 실행규칙 아님) ===")
s=np.sort(r)
for n in (10,25,50,100,200):
    print(f"  최악 {n:3d}건 제외 시 기대값 {s[n:].mean():+6.2f}%  (전체 {r.mean():+.2f}%)")
