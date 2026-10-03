"""prereg #38 PREREG_SHORT_R30_SPLIT.md"""
import pickle,os,numpy as np
D='research/m5bt'
d=pickle.load(open(f'{D}/wide_rows.pkl','rb'));a=d['a'];sc=np.asarray(d['sc'],dtype=float)
net=np.asarray(a['net'],dtype=float)/100.0;sym=a['sym'];t0=np.asarray(a['t0'],dtype=np.int64)
r30=np.full(len(a),np.nan);cache={}
for i,(s,t) in enumerate(zip(sym,t0)):
    s=str(s)
    if s not in cache:
        try: z=np.load(f'{D}/pq/{s}.npz');cache={s:(z['t'],z['c'])}
        except Exception: cache={s:None}
    v=cache[s]
    if v is None: continue
    tt,cc=v;j=int(np.searchsorted(tt,t));k=int(np.searchsorted(tt,t-30*86400000))
    if j>=len(tt) or int(tt[j])!=int(t) or k<=0 or k>=len(tt) or (int(tt[k])-(t-30*86400000))>3600000*6: continue
    r30[i]=cc[j]/cc[k]-1
ok=~np.isnan(r30);print(f'30일 이력 확보 {ok.sum()}/{len(a)}')
x=net[ok];r=r30[ok];day=(t0[ok]//86400000);S=sc[ok]
def diff_ci(m1,m2,seed=20261003):
    days=np.unique(day);idx={dd:np.nonzero(day==dd)[0] for dd in days};rng=np.random.default_rng(seed);ds=[]
    for _ in range(4000):
        sel=np.concatenate([idx[days[p]] for p in rng.integers(0,len(days),len(days))])
        a1=x[sel][m1[sel]];a2=x[sel][m2[sel]]
        if len(a1) and len(a2): ds.append(a1.mean()-a2.mean())
    return np.percentile(ds,[2.5,97.5])
up=r>0;dn=r<=0
print(f'r30>0: n={up.sum()} 평균 {x[up].mean()*100:+.2f}% 중앙 {np.median(x[up])*100:+.2f}% 승률 {(x[up]>0).mean()*100:.0f}% 최악 {x[up].min()*100:+.0f}%')
print(f'r30<=0: n={dn.sum()} 평균 {x[dn].mean()*100:+.2f}% 중앙 {np.median(x[dn])*100:+.2f}% 승률 {(x[dn]>0).mean()*100:.0f}% 최악 {x[dn].min()*100:+.0f}%')
df=x[up].mean()-x[dn].mean();lo,hi=diff_ci(up,dn)
print(f'차이(r30>0 − r30<=0) {df*100:+.2f}%p  95% CI [{lo*100:+.2f},{hi*100:+.2f}]')
med=np.median(day)
for nm,m in (('전반',day<=med),('후반',day>med)):
    a1=x[m&up];a2=x[m&dn];print(f'  {nm}: r30>0 {a1.mean()*100:+.2f}%(n={len(a1)}) r30<=0 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {(a1.mean()-a2.mean())*100:+.2f}%p')
c=S>=38.1
if c.sum()>100: 
    a1=x[c&up];a2=x[c&dn];print(f'  CUSUM>=38.1: r30>0 {a1.mean()*100:+.2f}%(n={len(a1)}) r30<=0 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {(a1.mean()-a2.mean())*100:+.2f}%p')
print('판정:','성립' if df>0 and lo>0 and up.sum()>=300 and dn.sum()>=300 else '기각')
