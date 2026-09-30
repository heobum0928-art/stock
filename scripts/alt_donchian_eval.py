"""prereg #12 PREREG_ALT_DONCHIAN.md"""
import os, glob, numpy as np
from datetime import datetime, timezone
EN,EX,TOPN,LB,COST=20,10,30,30,0.0012
def build_bull():
    files=sorted(glob.glob('research/m5bt/pq_bull/*.npz')); syms=[os.path.basename(f)[:-4] for f in files]
    d0=int(datetime(2023,1,1,tzinfo=timezone.utc).timestamp())//86400; d1=int(datetime(2025,6,30,tzinfo=timezone.utc).timestamp())//86400
    nd=np.arange(d0,d1+1); C=np.full((len(syms),len(nd)),np.nan); V=C.copy()
    for i,f in enumerate(files):
        z=np.load(f); t=z['t']//1000//86400
        for d in np.unique(t):
            m=t==d; j=int(d)-d0
            if 0<=j<len(nd): C[i,j]=z['c'][m][-1]; V[i,j]=z['qv'][m].sum()
    return nd,syms,C,V
def build_b():
    z=np.load('research/m5bt/_quiet_daily_pq.npz',allow_pickle=True); return z['days'],z['syms'].tolist(),z['C'],z['V']
def trades(nd,syms,C,V,start):
    out=[]; bi=syms.index('BTCUSDT') if 'BTCUSDT' in syms else -1
    n=len(nd)
    for i in range(len(syms)):
        if i==bi: continue
        c=C[i]; pos=None
        for j in range(max(EN,LB),n):
            if np.isnan(c[j]): 
                continue
            if pos is None:
                if nd[j]<start: continue
                hist=c[j-EN:j]
                if np.isnan(hist).any() or c[j]<=hist.max(): continue
                win=V[:,j-LB:j]; mv=np.nansum(win,axis=0) if False else np.nansum(win,axis=1)
                mv[bi]=-1 if bi>=0 else 0
                mv=np.where(np.isnan(V[:,j-1]),-1,mv)
                if i not in np.argsort(-mv)[:TOPN]: continue
                pos=(j,c[j])
            else:
                lo=c[j-EX:j]
                if np.isnan(lo).any(): continue
                if c[j]<lo.min():
                    out.append((int(nd[pos[0]]),c[j]/pos[1]-1-COST)); pos=None
        if pos is not None:
            last=c[~np.isnan(c)][-1]; out.append((int(nd[pos[0]]),last/pos[1]-1-COST))
    return out
A=trades(*build_bull(),start=0)
B=trades(*build_b(),start=0)
def boot(tr):
    d=np.array([t[0] for t in tr]);x=np.array([t[1] for t in tr]);wk=d//7
    ks=np.unique(wk);g={k:x[wk==k] for k in ks};rng=np.random.default_rng(20260930);ms=[]
    for _ in range(4000):
        s=np.concatenate([g[k] for k in rng.choice(ks,len(ks))]);ms.append(s.mean())
    return np.percentile(ms,[2.5,97.5])
def rep(name,tr):
    x=np.array([t[1] for t in tr]);w=x[x>0];l=x[x<=0]
    top=np.sort(x)[::-1][:10].sum()/x[x>0].sum()
    print(f'{name}: n={len(x)} 평균 {x.mean()*100:+.2f}% 중앙 {np.median(x)*100:+.2f}% 승률 {(x>0).mean()*100:.0f}% 평균이익 {w.mean()*100:+.1f}% 평균손실 {l.mean()*100:+.1f}% 상위10건 비중 {top*100:.0f}%')
rep('A 2023-25',A);rep('B 2025-26',B);rep('전체',A+B)
al=A+B;lo,hi=boot(al);m=np.mean([t[1] for t in al])
print(f'전체 CI [{lo*100:+.2f},{hi*100:+.2f}]')
ok=len(al)>=100 and m>0 and lo>0 and np.mean([t[1] for t in A])>0 and np.mean([t[1] for t in B])>0
print('판정:', '판별 불가' if len(al)<100 else ('성립' if ok else '기각'))
