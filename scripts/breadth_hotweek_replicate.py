"""prereg #11 PREREG_BREADTH_HOTWEEK_REPLICATE.md  (pq_bull 2023-01~2025-06)"""
import os, glob, numpy as np
from datetime import datetime, timezone
D='research/m5bt/pq_bull'
LB,TOPN,STEP,COST=30,30,7,0.0012
files=sorted(glob.glob(D+'/*.npz')); syms=[os.path.basename(f)[:-4] for f in files]
d0=int(datetime(2023,1,1,tzinfo=timezone.utc).timestamp())//86400
d1=int(datetime(2025,6,30,tzinfo=timezone.utc).timestamp())//86400
nd=np.arange(d0,d1+1); C=np.full((len(syms),len(nd)),np.nan); V=C.copy()
for i,f in enumerate(files):
    z=np.load(f); t=z['t']//1000//86400; c=z['c']; qv=z['qv']
    for d in np.unique(t):
        m=t==d; j=int(d)-d0
        if 0<=j<len(nd): C[i,j]=c[m][-1]; V[i,j]=qv[m].sum()
bi=syms.index('BTCUSDT'); prev={}; rows=[]
for j in range(LB+1,len(nd)-STEP,STEP):
    win=V[:,j-LB:j]; cnt=(~np.isnan(win)).sum(1)
    mv=np.where(cnt>=25,np.nansum(win,1)/np.maximum(cnt,1)*LB,np.nan)
    ok=~np.isnan(mv)&~np.isnan(C[:,j])&~np.isnan(C[:,j-LB])&~np.isnan(C[:,j-7])&~np.isnan(C[:,j+STEP]); ok[bi]=False
    cand=np.nonzero(ok)[0]
    if len(cand)<TOPN: continue
    uni=cand[np.argsort(-mv[cand])[:TOPN]]
    mom=C[uni,j]/C[uni,j-LB]-1; fwd=C[uni,j+STEP]/C[uni,j]-1
    breadth=(C[uni,j]/C[uni,j-7]-1>0).mean()
    w={int(u):1/TOPN for u,m in zip(uni,mom) if m<0}
    turn=sum(abs(w.get(k,0)-prev.get(k,0)) for k in set(w)|set(prev)); prev=w
    r=sum(-w[int(u)]*f for u,f in zip(uni,fwd) if int(u) in w)-turn*COST
    rows.append((int(nd[j]),breadth,r,len(w)))
dd=np.array([r[0] for r in rows]);B=np.array([r[1] for r in rows]);R=np.array([r[2] for r in rows])
d2s=lambda d:datetime.fromtimestamp(int(d)*86400,timezone.utc).strftime('%Y-%m-%d')
hot=B>=0.70
print(f'{d2s(dd[0])}~{d2s(dd[-1]+STEP)} 주={len(R)} 뜨거운 주={hot.sum()}  전체 평균 {R.mean()*100:+.3f}%/주')
print(f'뜨거운 평균 {R[hot].mean()*100:+.3f}%  그 외 {R[~hot].mean()*100:+.3f}%  차이 {(R[hot].mean()-R[~hot].mean())*100:+.3f}%p' if hot.sum() else '뜨거운 주 없음')
if hot.sum()>=12:
    rng=np.random.default_rng(20260930);x=R[hot]
    ms=[x[rng.integers(0,len(x),len(x))].mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    print(f'뜨거운 주 95% CI [{lo*100:+.3f},{hi*100:+.3f}]  판정:', '성립' if x.mean()>0 and lo>0 else '기각')
    top=np.argsort(-np.abs(x))[:3]; print('최대기여 뜨거운 주 수익:',[f'{v*100:+.1f}%' for v in x[top]])
else: print('판정: 판별 불가(뜨거운 주 12주 미만)')
