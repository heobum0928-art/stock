"""prereg #42 PREREG_NR7_RANGE_SIZE.md"""
import glob,os,json,datetime as dt,numpy as np
from scipy.stats import spearmanr
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
def full(dirn):
    D={}
    for f in glob.glob(S+dirn+'/d_*.json'):
        s=os.path.basename(f)[2:-5]
        D[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(k[2],k[3],k[4]) for k in json.load(open(f))}
    return D
EVB=json.load(open(S+'ext_B.json'));NEED={e[1] for e in EVB}
Bd={}
for f in sorted(glob.glob('research/m5bt/pq_bull/*.npz')):
    s=os.path.basename(f)[:-4]
    if s not in NEED: continue
    z=np.load(f);t=z['t']//1000;hh=z['h'];ll=z['l'];cc=z['c'];day=t//86400;u,idx=np.unique(day,return_index=True);e=np.r_[idx[1:],len(t)]
    Bd[s]={dt.date(1970,1,1)+dt.timedelta(int(a)):(hh[i:b].max(),ll[i:b].min(),cc[b-1]) for a,i,b in zip(u,idx,e)}
DAY={'C':full('nr7hC'),'B':Bd,'A':full('nr7h')}
EV={'C':json.load(open(S+'ext_C.json')),'B':json.load(open(S+'ext_B.json')),'A':json.load(open(S+'ext_A.json'))}
rows=[]
for p,ev in EV.items():
    for (d,s,sd,rs,rc,adv,adv_stop) in ev:
        if sd!='S': continue
        dd=dt.date.fromisoformat(d);v=DAY[p].get(s,{}).get(dd-dt.timedelta(1))
        if not v: continue
        rows.append((p,dd.toordinal(),(v[0]-v[1])/v[2],rs-0.0012))
P=np.array([r[0] for r in rows]);Dd=np.array([r[1] for r in rows]);Rg=np.array([r[2] for r in rows]);X=np.array([r[3] for r in rows])
print(f'확보 {len(X)}건')
rho,_=spearmanr(Rg,X)
days=np.unique(Dd);idx={d:np.nonzero(Dd==d)[0] for d in days};rng=np.random.default_rng(20261004);rs_=[]
for _ in range(1000):
    sel=np.concatenate([idx[days[q]] for q in rng.integers(0,len(days),len(days))])
    rs_.append(spearmanr(Rg[sel],X[sel])[0])
lo,hi=np.percentile(rs_,[2.5,97.5])
print(f'풀링 ρ={rho:+.3f}  95% CI [{lo:+.3f},{hi:+.3f}]')
ok=True
for p in 'CBA':
    m=P==p;r,_=spearmanr(Rg[m],X[m]);ok&=r>0
    q=np.quantile(Rg[m],[1/3,2/3]);t1=X[m&(Rg<=q[0])].mean();t2=X[m&(Rg>q[0])&(Rg<=q[1])].mean();t3=X[m&(Rg>q[1])].mean()
    print(f'  기간 {p}: ρ={r:+.3f} 값폭 평균 {Rg[m].mean()*100:.1f}% 중앙 {np.median(Rg[m])*100:.1f}% | 3분위 평균 순수익 작음 {t1*100:+.2f}% 중간 {t2*100:+.2f}% 큼 {t3*100:+.2f}%')
print('판정:','성립' if rho>0 and lo>0 and ok else '기각')
