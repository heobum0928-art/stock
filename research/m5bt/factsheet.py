import numpy as np, datetime as dt
from scipy import stats
L=lambda t: np.load('base_%s.npz'%t,allow_pickle=True)
R,N=L('real'),L('rand')
r=R['ret_opt']*100; n=N['ret_opt']*100
mae=R['mae'].astype(float); mfe=R['mfe'].astype(float)
print("### A. 기본 (증거금 기준 %, 레버리지 2배 반영, 펀딩·수수료 포함)")
print(f"신호진입 n={len(r)}  평균 {r.mean():+.2f}  중앙 {np.median(r):+.2f}  승률 {(r>0).mean()*100:.1f}%  왜도 {stats.skew(r):+.2f}")
print(f"무작위진입 n={len(n)}  평균 {n.mean():+.2f}  중앙 {np.median(n):+.2f}  승률 {(n>0).mean()*100:.1f}%")
print(f"평균 승 {r[r>0].mean():+.2f} / 평균 패 {r[r<=0].mean():+.2f}")
q=np.percentile(r,[1,5,10,25,50,75,90,95,99])
print("분위 1/5/10/25/50/75/90/95/99: "+" ".join(f"{x:+.1f}" for x in q))
print("\n### B. 청산사유별 (신호진입)")
for k in np.unique(R['kind']):
    m=R['kind']==k; print(f"  {k:8s} {m.sum():5d}건 ({m.mean()*100:5.1f}%)  평균 {r[m].mean():+8.2f}  전체기여 {r[m].sum()/len(r):+7.2f}%p")
print("\n### C. 펀딩")
print(f"  신호진입 펀딩기여 {(r-R['ret_opt_nf']*100).mean():+.2f}%p  /  무작위 {(n-N['ret_opt_nf']*100).mean():+.2f}%p")
print("\n### D. 역행폭(MAE) 구간별 — 회복은 실재한다")
for a,b in ((0,10),(10,20),(20,30),(30,35),(35,40),(40,999)):
    m=(mae>=a)&(mae<b)
    if m.sum()<5: continue
    print(f"  MAE {a:>2}~{b if b<999 else '∞':<4} n={m.sum():4d}  최종플러스 {(r[m]>0).mean()*100:5.1f}%  평균 {r[m].mean():+8.2f}")
print(f"\n  MAE 평균: 신호 {mae.mean():.2f}%  무작위 {N['mae'].astype(float).mean():.2f}%  (명목)")
print(f"  MFE 평균: 신호 {mfe.mean():.2f}%  무작위 {N['mfe'].astype(float).mean():.2f}%  (명목)")
print("\n### E. 레버리지별 강제청산선과 피해")
MMR=.05; liq=lambda Lv:(1-Lv*MMR)/(Lv*(1+MMR))*100
for Lv in (1,1.5,2,3,5,10):
    a=liq(Lv); m=mae>=a
    print(f"  {Lv:4.1f}배  청산선 역행 {a:6.2f}%  청산되는 신호 {m.sum():4d}건({m.mean()*100:4.1f}%)  그중 현행규칙에선 플러스로 끝났던 것 {(r[m]>0).mean()*100:4.1f}%")
print("\n### F. -40% 절벽")
h=mae>=40; g=mae>=liq(2)
print(f"  -40% 도달 {h.sum()}건 → 강제청산선(-42.86%)까지 간 것 {g.sum()}건 = {g.sum()/h.sum()*100:.1f}%")
print("\n### G. 단일 날짜 집중도")
day=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m-%d') for x in R['t0'].astype(float)])
u,c=np.unique(day,return_counts=True); o=np.argsort(-c)[:5]
for i in o: print(f"  {u[i]}  {c[i]}건 ({c[i]/len(r)*100:.1f}%)  평균 {r[day==u[i]].mean():+.2f}  무작위 같은날 평균 {n[np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m-%d') for x in N['t0'].astype(float)])==u[i]].mean():+.2f}")
