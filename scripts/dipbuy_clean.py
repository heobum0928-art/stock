"""prereg #24 PREREG_DIPBUY_CLEAN.md"""
import requests, datetime as dt, numpy as np, time, json, os
F='https://fapi.binance.com'
C='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/dip/'
os.makedirs(C,exist_ok=True)
info=requests.get(F+'/fapi/v1/exchangeInfo',timeout=30).json()
perps=[s['symbol'] for s in info['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL']
EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT'}
D0=dt.date(2026,1,1)
def daily(s):
    p=C+s+'.json'
    if os.path.exists(p): return json.load(open(p))
    r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=int(dt.datetime(2026,1,1,tzinfo=dt.timezone.utc).timestamp()*1000),limit=400),timeout=30).json()
    out=[(k[0],float(k[1]),float(k[4]),float(k[7])) for k in r] if isinstance(r,list) else []
    json.dump(out,open(p,'w'));time.sleep(0.04);return out
def fund(s,t0,t1):
    p=C+s+'_f.json'
    if os.path.exists(p): return json.load(open(p))
    out=[];st=t0
    while st<t1:
        r=requests.get(F+'/fapi/v1/fundingRate',params=dict(symbol=s,startTime=st,endTime=t1,limit=1000),timeout=30).json()
        if not r: break
        out+=[(x['fundingTime'],float(x['fundingRate'])) for x in r];st=r[-1]['fundingTime']+1
        if len(r)<1000: break
    json.dump(out,open(p,'w'));return out
DAY={s:{dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():k for k in daily(s) if k} for s in perps if s not in EX}
DAY={s:v for s,v in DAY.items() if len(v)>60}
ts=lambda d:int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000)
ev=[]
for d in [dt.date(2026,4,1)+dt.timedelta(i) for i in range(183)]:
    vols={}
    for s,v in DAY.items():
        w=[v.get(d-dt.timedelta(i)) for i in range(1,31)]
        if all(w): vols[s]=sum(k[3] for k in w)
    for s in sorted(vols,key=vols.get,reverse=True)[:15]:
        v=DAY[s];h=[v.get(d-dt.timedelta(i)) for i in range(1,51)]
        if any(x is None for x in h) or d not in v or d+dt.timedelta(1) not in v: continue
        # 시가(00:00 UTC) 기준: 일봉 시가=그날 00:00 가격
        ma=np.mean([x[1] for x in h]);o_d=v[d][1];o_p=v[d-dt.timedelta(1)][1];o_n=v[d+dt.timedelta(1)][1]
        if not o_d>ma: continue
        if o_d/o_p-1>-0.03: continue
        f=sum(x for t,x in fund(s,ts(d),ts(d)+86400000) if ts(d)<=t<ts(d)+86400000)
        ev.append((d,s,o_n/o_d-1-f-0.0012))
print(len(DAY),'종목, 건수',len(ev))
def rep(nm,e):
    x=np.array([a[2] for a in e]);
    if len(x)==0: print(nm,'건수 0');return x
    print(f'{nm}: n={len(x)} 평균 {x.mean()*100:+.3f}% 중앙 {np.median(x)*100:+.3f}% 승률 {(x>0).mean()*100:.0f}% 최대 {x.max()*100:+.1f}% 최소 {x.min()*100:+.1f}% 상위5 이익비중 {np.sort(x)[::-1][:5].clip(0).sum()/max(x.clip(0).sum(),1e-9)*100:.0f}%');return x
A=[e for e in ev if e[0]<dt.date(2026,7,1)];B=[e for e in ev if e[0]>=dt.date(2026,7,1)]
xa=rep('A 4~6월',A);xb=rep('B 7~9월',B);x=np.r_[xa,xb]
dd=np.array([e[0].toordinal() for e in ev]);ks=np.unique(dd);g={k:np.array([e[2] for e in ev if e[0].toordinal()==k]) for k in ks};rng=np.random.default_rng(20261001)
ms=[np.concatenate([g[k] for k in rng.choice(ks,len(ks))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
print(f'합친 평균 {x.mean()*100:+.3f}% CI [{lo*100:+.3f},{hi*100:+.3f}]  종목 수 {len(set(e[1] for e in ev))}')
ok=len(xa)>=30 and len(xb)>=30
print('판정:','판별 불가' if not ok else ('성립' if xa.mean()>0 and xb.mean()>0 and lo>0 else '기각'))
