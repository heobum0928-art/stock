"""prereg #53 PREREG_SHORT_QV24.md"""
import pickle,numpy as np
D='research/m5bt'
d=pickle.load(open(f'{D}/wide_rows.pkl','rb'));a=d['a'];sc=np.asarray(d['sc'],dtype=float)
net=np.asarray(a['net'],dtype=float)/100.0;sym=a['sym'];t0=np.asarray(a['t0'],dtype=np.int64)
q=np.full(len(a),np.nan);cache={}
for i,(s,t) in enumerate(zip(sym,t0)):
    s=str(s)
    if s not in cache:
        try: z=np.load(f'{D}/pq/{s}.npz');cache={s:(z['t'],z['qv'])}
        except Exception: cache={s:None}
    v=cache[s]
    if v is None: continue
    tt,qq=v;j=int(np.searchsorted(tt,t))
    if j>=len(tt) or int(tt[j])!=int(t) or j<288: continue
    if int(tt[j])-int(tt[j-288])>288*300000+600000: continue
    q[i]=qq[j-288:j].sum()
ok=~np.isnan(q);print(f'24h 이력 확보 {ok.sum()}/{len(a)}')
x=net[ok];v=q[ok];day=(t0[ok]//86400000);S=sc[ok]
med=np.median(v);print(f'qv24 중앙값 {med:,.0f} USDT')
def diff_ci(m1,m2,seed=20261008):
    days=np.unique(day);idx={dd:np.nonzero(day==dd)[0] for dd in days};rng=np.random.default_rng(seed);ds=[]
    for _ in range(4000):
        sel=np.concatenate([idx[days[p]] for p in rng.integers(0,len(days),len(days))])
        a1=x[sel][m1[sel]];a2=x[sel][m2[sel]]
        if len(a1) and len(a2): ds.append(a1.mean()-a2.mean())
    return np.percentile(ds,[2.5,97.5])
lo_=v<=med;hi_=v>med
for nm,m in (('작은(<=중앙)',lo_),('큰(>중앙)',hi_)):
    print(f'{nm}: n={m.sum()} 평균 {x[m].mean()*100:+.2f}% 중앙 {np.median(x[m])*100:+.2f}% 승률 {(x[m]>0).mean()*100:.0f}% 최악 {x[m].min()*100:+.0f}%')
df=x[lo_].mean()-x[hi_].mean();lo,hi=diff_ci(lo_,hi_);half=[]
print(f'차이(작은 − 큰) {df*100:+.2f}%p  95% CI [{lo*100:+.2f},{hi*100:+.2f}]')
dmed=np.median(day)
for nm,m in (('전반',day<=dmed),('후반',day>dmed)):
    a1=x[m&lo_];a2=x[m&hi_];half.append(a1.mean()-a2.mean());print(f'  {nm}: 작은 {a1.mean()*100:+.2f}%(n={len(a1)}) 큰 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {(a1.mean()-a2.mean())*100:+.2f}%p')
c=S>=38.1
if c.sum()>100:
    a1=x[c&lo_];a2=x[c&hi_];print(f'  CUSUM>=38.1: 작은 {a1.mean()*100:+.2f}%(n={len(a1)}) 큰 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {(a1.mean()-a2.mean())*100:+.2f}%p')
t1,t2=np.percentile(v,[33.3,66.7])
for nm,m in (('하',v<=t1),('중',(v>t1)&(v<=t2)),('상',v>t2)):
    print(f'  3분위 {nm}: n={m.sum()} 평균 {x[m].mean()*100:+.2f}% 승률 {(x[m]>0).mean()*100:.0f}%')
print('판정:','판별 불가' if lo_.sum()<300 or hi_.sum()<300 else ('성립' if df>0 and lo>0 and all(h>0 for h in half) else '기각'))
