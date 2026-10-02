"""prereg #31 PREREG_BASKETSTOP_OOS.md  (pq_bull 2023-01~2025-06)"""
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
    ok=~np.isnan(mv)&~np.isnan(C[:,j])&~np.isnan(C[:,j-LB])&~np.isnan(C[:,j+STEP]); ok[bi]=False
    cand=np.nonzero(ok)[0]
    if len(cand)<TOPN: continue
    uni=cand[np.argsort(-mv[cand])[:TOPN]]
    mom=C[uni,j]/C[uni,j-LB]-1
    w={int(u):1/TOPN for u,m in zip(uni,mom) if m<0}
    turn=sum(abs(w.get(k,0)-prev.get(k,0)) for k in set(w)|set(prev)); prev=w
    path=[]
    for k in range(1,STEP+1):
        path.append(-sum(w[u]*(C[u,j+k]/C[u,j]-1) for u in w if not np.isnan(C[u,j+k])))
    base=path[-1]-turn*COST;r=base;hit=False
    for pv in path:
        if pv-turn*COST<=-0.06: r=pv-turn*COST-sum(w.values())*COST;hit=True;break
    rows.append((int(nd[j]),r,base,hit))
dd=np.array([x[0] for x in rows]);R=np.array([x[1] for x in rows]);Bs=np.array([x[2] for x in rows])
d2s=lambda d:datetime.fromtimestamp(int(d)*86400,timezone.utc).strftime('%Y-%m-%d')
months=np.array([d2s(d)[:7] for d in dd]);yrs=len(R)*STEP/365;res={}
for nm,x in (('기준선',Bs),('바구니 손절',R)):
    e=np.cumprod(1+x);mm={mo:np.prod(1+x[months==mo])-1 for mo in sorted(set(months))};wm=min(mm,key=mm.get)
    res[nm]=(e[-1],(e/np.maximum.accumulate(e)-1).min())
    print(f'{nm}: 누적 {e[-1]:.2f}배 연복리 {(e[-1]**(1/yrs)-1)*100:+.0f}% MDD {res[nm][1]*100:.0f}% 월 양수 {sum(v>0 for v in mm.values())}/{len(mm)} 최악 달 {wm} {mm[wm]*100:+.0f}%')
print(f'{d2s(dd[0])}~{d2s(dd[-1]+STEP)} {len(R)}주, 손절 발동 {sum(x[3] for x in rows)}주')
for y in sorted(set(m[:4] for m in months)):
    k=np.array([m[:4]==y for m in months]);print(f'  {y}: 기준선 {np.prod(1+Bs[k])-1:+.0%} 손절 {np.prod(1+R[k])-1:+.0%}')
a,b=res['바구니 손절'],res['기준선']
print('판정:','성립' if a[0]>1 and a[0]>b[0] and a[1]>b[1] else '기각')
