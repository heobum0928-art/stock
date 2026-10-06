"""prereg #45 PREREG_WEEKEND_PUMPSHORT.md"""
import pickle,numpy as np,datetime as dt
d=pickle.load(open('research/m5bt/wide_rows.pkl','rb'));a=d['a'];sc=np.asarray(d['sc'],dtype=float)
net=np.asarray(a['net'],dtype=float)/100.0;t0=np.asarray(a['t0'],dtype=np.int64)
kst=[dt.datetime.fromtimestamp(t/1000,dt.timezone(dt.timedelta(hours=9))) for t in t0]
wd=np.array([k.weekday() for k in kst]);we=wd>=5;day=np.array([k.date().toordinal() for k in kst])
print(f'신호 {len(net)}건 / 주말 {we.sum()}건 평일 {(~we).sum()}건')
def ci(m1,m2,sel_mask=None):
    days=np.unique(day);idx={x:np.nonzero(day==x)[0] for x in days};rng=np.random.default_rng(20261006);ds=[]
    for _ in range(4000):
        sel=np.concatenate([idx[days[q]] for q in rng.integers(0,len(days),len(days))])
        a1=net[sel][m1[sel]];a2=net[sel][m2[sel]]
        if len(a1) and len(a2): ds.append(a1.mean()-a2.mean())
    return np.percentile(ds,[2.5,97.5])
df=net[we].mean()-net[~we].mean();lo,hi=ci(we,~we)
print(f'주말 평균 {net[we].mean()*100:+.2f}% 승률 {(net[we]>0).mean()*100:.0f}% 최악 {net[we].min()*100:+.0f}% | 평일 평균 {net[~we].mean()*100:+.2f}% 승률 {(net[~we]>0).mean()*100:.0f}%')
print(f'차이(주말−평일) {df*100:+.2f}%p  95% CI [{lo*100:+.2f},{hi*100:+.2f}]')
med=np.median(day);ok=True
for nm,h in (('전반',day<=med),('후반',day>med)):
    x=net[we&h].mean()-net[~we&h].mean();ok&=x>0;print(f'  {nm}: 주말 n={(we&h).sum()} {net[we&h].mean()*100:+.2f}% 평일 n={(~we&h).sum()} {net[~we&h].mean()*100:+.2f}% 차이 {x*100:+.2f}%p')
c=sc>=38.1
if (c&we).sum()>30: print(f'  CUSUM>=38.1: 주말 n={(c&we).sum()} {net[c&we].mean()*100:+.2f}% 평일 n={(c&~we).sum()} {net[c&~we].mean()*100:+.2f}% 차이 {(net[c&we].mean()-net[c&~we].mean())*100:+.2f}%p')
print('  요일별(월~일):',[f'{net[wd==i].mean()*100:+.1f}%(n={(wd==i).sum()})' for i in range(7)])
print('판정:','판별 불가' if we.sum()<300 else ('성립' if df>0 and lo>0 and ok else '기각'))
