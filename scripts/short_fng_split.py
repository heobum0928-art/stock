"""prereg #44 PREREG_SHORT_FNG_SPLIT.md"""
import pickle,numpy as np,datetime as dt
D='research/m5bt'
d=pickle.load(open(f'{D}/wide_rows.pkl','rb'));a=d['a'];sc=np.asarray(d['sc'],dtype=float)
net=np.asarray(a['net'],dtype=float)/100.0;t0=np.asarray(a['t0'],dtype=np.int64)
fng={}
for ln in open('data/fear_greed_daily.csv').read().splitlines()[1:]:
    k,v=ln.split(',');fng[k]=int(v)
day=t0//86400000
prev=np.array([fng.get((dt.datetime.utcfromtimestamp(int(dd)*86400)-dt.timedelta(days=1)).strftime('%Y-%m-%d'),-1) for dd in day])
ok=prev>=0;print(f'지수 확보 {ok.sum()}/{len(a)}')
x=net[ok];f=prev[ok];dy=day[ok];S=sc[ok]
def diff_ci(m1,m2,seed=20261005):
    days=np.unique(dy);idx={q:np.nonzero(dy==q)[0] for q in days};rng=np.random.default_rng(seed);ds=[]
    for _ in range(4000):
        sel=np.concatenate([idx[days[p]] for p in rng.integers(0,len(days),len(days))])
        a1=x[sel][m1[sel]];a2=x[sel][m2[sel]]
        if len(a1) and len(a2): ds.append(a1.mean()-a2.mean())
    return np.percentile(ds,[2.5,97.5])
g=f>50;l=f<=50
def show(nm,m): print(f'{nm}: n={m.sum()} 날짜 {len(np.unique(dy[m]))} 평균 {x[m].mean()*100:+.2f}% 중앙 {np.median(x[m])*100:+.2f}% 승률 {(x[m]>0).mean()*100:.0f}% 최악 {x[m].min()*100:+.0f}%')
show('탐욕(>50)',g);show('공포·중립(≤50)',l)
df=x[g].mean()-x[l].mean();lo,hi=diff_ci(g,l)
print(f'차이(탐욕 − 공포) {df*100:+.2f}%p  95% CI [{lo*100:+.2f},{hi*100:+.2f}]')
med=np.median(dy)
for nm,m in (('전반',dy<=med),('후반',dy>med)):
    a1=x[m&g];a2=x[m&l]
    if len(a1) and len(a2): print(f'  {nm}: 탐욕 {a1.mean()*100:+.2f}%(n={len(a1)}) 공포 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {(a1.mean()-a2.mean())*100:+.2f}%p')
c=S>=38.1
if c.sum()>100:
    a1=x[c&g];a2=x[c&l];print(f'  CUSUM>=38.1: 탐욕 {a1.mean()*100:+.2f}%(n={len(a1)}) 공포 {a2.mean()*100:+.2f}%(n={len(a2)}) 차이 {(a1.mean()-a2.mean())*100:+.2f}%p')
print('판정:','성립' if df>0 and lo>0 and g.sum()>=300 and l.sum()>=300 else '기각')
