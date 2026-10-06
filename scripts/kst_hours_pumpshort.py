"""prereg #46 PREREG_KST_HOURS_PUMPSHORT.md"""
import pickle,numpy as np,datetime as dt
d=pickle.load(open('research/m5bt/wide_rows.pkl','rb'));a=d['a'];sc=np.asarray(d['sc'],dtype=float)
net=np.asarray(a['net'],dtype=float)/100.0;t0=np.asarray(a['t0'],dtype=np.int64)
kst=[dt.datetime.fromtimestamp(t/1000,dt.timezone(dt.timedelta(hours=9))) for t in t0]
hr=np.array([k.hour for k in kst]);act=hr>=9;day=np.array([k.date().toordinal() for k in kst])
print(f'신호 {len(net)}건 / 활동 {act.sum()}건 비활동 {(~act).sum()}건')
def ci(m1,m2):
    days=np.unique(day);idx={x:np.nonzero(day==x)[0] for x in days};rng=np.random.default_rng(20261006);ds=[]
    for _ in range(4000):
        sel=np.concatenate([idx[days[q]] for q in rng.integers(0,len(days),len(days))])
        a1=net[sel][m1[sel]];a2=net[sel][m2[sel]]
        if len(a1) and len(a2): ds.append(a1.mean()-a2.mean())
    return np.percentile(ds,[2.5,97.5])
df=net[act].mean()-net[~act].mean();lo,hi=ci(act,~act)
print(f'활동 평균 {net[act].mean()*100:+.2f}% 승률 {(net[act]>0).mean()*100:.0f}% 최악 {net[act].min()*100:+.0f}% | 비활동 평균 {net[~act].mean()*100:+.2f}% 승률 {(net[~act]>0).mean()*100:.0f}%')
print(f'차이(활동−비활동) {df*100:+.2f}%p  95% CI [{lo*100:+.2f},{hi*100:+.2f}]')
med=np.median(day);ok=True
for nm,h in (('전반',day<=med),('후반',day>med)):
    x=net[act&h].mean()-net[~act&h].mean();ok&=x>0;print(f'  {nm}: 활동 n={(act&h).sum()} {net[act&h].mean()*100:+.2f}% 비활동 n={(~act&h).sum()} {net[~act&h].mean()*100:+.2f}% 차이 {x*100:+.2f}%p')
c=sc>=38.1
if (c&act).sum()>30 and (c&~act).sum()>30: print(f'  CUSUM>=38.1: 활동 n={(c&act).sum()} {net[c&act].mean()*100:+.2f}% 비활동 n={(c&~act).sum()} {net[c&~act].mean()*100:+.2f}% 차이 {(net[c&act].mean()-net[c&~act].mean())*100:+.2f}%p')
print('  시별(KST 0~23):',' '.join(f'{h}:{net[hr==h].mean()*100:+.0f}%({(hr==h).sum()})' for h in range(24) if (hr==h).sum()))
print('판정:','판별 불가' if min(act.sum(),(~act).sum())<300 else ('성립' if df>0 and lo>0 and ok else '기각'))
