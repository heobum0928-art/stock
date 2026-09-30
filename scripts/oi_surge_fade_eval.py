"""prereg #18 PREREG_OI_SURGE_FADE.md"""
import io,zipfile,os,json,datetime as dt,numpy as np,requests
from concurrent.futures import ThreadPoolExecutor
C='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/oi/'
os.makedirs(C,exist_ok=True)
def get(sym,d):
    p=f'{C}{sym}_{d}.json'
    if os.path.exists(p): return json.load(open(p))
    u=f'https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{d}.zip'
    for _ in range(3):
        try:
            r=requests.get(u,timeout=30)
            if r.status_code==404: out=[]; break
            if r.status_code==200:
                z=zipfile.ZipFile(io.BytesIO(r.content));rows=z.open(z.namelist()[0]).read().decode().split('\n')[1:]
                out=[(x.split(',')[0],float(x.split(',')[2])) for x in rows if x.count(',')>=3 and x.split(',')[0][14:16]=='00']
                break
        except Exception: pass
    else: out=[]
    json.dump(out,open(p,'w'));return out
days=[(dt.date(2023,6,1)+dt.timedelta(i)).isoformat() for i in range((dt.date(2026,8,31)-dt.date(2023,6,1)).days+1)]
def hourly_oi(sym):
    with ThreadPoolExecutor(16) as ex: res=list(ex.map(lambda d:get(sym,d),days))
    o={}
    for r in res:
        for ts,v in r: o[int(dt.datetime.strptime(ts,'%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc).timestamp())]=v
    return o
def closes(sym):
    out={}
    for d in ('pq_bull','pq'):
        z=np.load(f'research/m5bt/{d}/{sym}.npz')
        for t,c in zip(z['t']//1000,z['c']): out[int(t)]=c
    return out
ev_all=[];per={}
for s in ('BTCUSDT','ETHUSDT','SOLUSDT'):
    oi=hourly_oi(s);cl=closes(s);ts=sorted(oi);ch={}
    for t in ts:
        p=t-4*3600
        if p in oi and oi[p]>0 and oi[t]>0: ch[t]=oi[t]/oi[p]-1
    hs=sorted(ch);last=-10**12;evs=[]
    arr=np.array([ch[t] for t in hs])
    for i,t in enumerate(hs):
        if i<90*24 or t<last+8*3600: continue
        thr=np.quantile(arr[i-90*24:i],0.9)
        if ch[t]<thr: continue
        pr0=cl.get(t-4*3600);pr1=cl.get(t)
        e=cl.get(t+300);x=cl.get(t+8*3600+300)
        if None in (pr0,pr1,e,x) or pr1==pr0: continue
        side=-1 if pr1>pr0 else 1
        r=side*(x/e-1)-0.0012
        evs.append((t//86400,r,side,int(t)));last=t
    per[s]=evs;ev_all+=evs
x=np.array([e[1] for e in ev_all]);n=len(x)
print('종목별:',{s:(len(v),round(float(np.mean([e[1] for e in v]))*100,3) if v else None) for s,v in per.items()})
if n:
    dd=np.array([e[0] for e in ev_all]);ks=np.unique(dd);g={k:x[dd==k] for k in ks};rng=np.random.default_rng(20260930)
    ms=[np.concatenate([g[k] for k in rng.choice(ks,len(ks))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    print(f'합산 n={n} 평균 {x.mean()*100:+.3f}% 중앙 {np.median(x)*100:+.3f}% 승률 {(x>0).mean()*100:.0f}% CI [{lo*100:+.3f},{hi*100:+.3f}]')
    for nm,sd in (('롱(하락 후)',1),('숏(상승 후)',-1)):
        m=np.array([e[2]==sd for e in ev_all]);print(f'  {nm}: n={m.sum()} 평균 {x[m].mean()*100:+.3f}%')
    print(f'  2025-07 이전 {x[[e[3]<1751328000 for e in ev_all]].mean()*100:+.3f}%  이후 {x[[e[3]>=1751328000 for e in ev_all]].mean()*100:+.3f}%')
    ok=n>=100 and x.mean()>0 and lo>0 and all(np.mean([e[1] for e in v])>0 for v in per.values() if v)
    print('판정:','판별 불가' if n<100 else ('성립' if ok else '기각'))
