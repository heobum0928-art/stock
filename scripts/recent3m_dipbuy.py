"""prereg #23 PREREG_RECENT3M_DIPBUY.md"""
import requests, datetime as dt, numpy as np, time
F='https://fapi.binance.com'
T0=int(dt.datetime(2026,4,1,tzinfo=dt.timezone.utc).timestamp()*1000); T1=int(dt.datetime(2026,10,1,tzinfo=dt.timezone.utc).timestamp()*1000)
def kl(sym,iv):
    out=[];s=T0
    while s<T1:
        r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=sym,interval=iv,startTime=s,endTime=T1-1,limit=1500),timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=r; s=r[-1][0]+1; time.sleep(0.05)
    return out
def fund(sym):
    out=[];s=T0
    while s<T1:
        r=requests.get(F+'/fapi/v1/fundingRate',params=dict(symbol=sym,startTime=s,endTime=T1-1,limit=1000),timeout=30).json()
        if not r: break
        out+=r; s=r[-1]['fundingTime']+1
        if len(r)<1000: break
    return out
info=requests.get(F+'/fapi/v1/exchangeInfo',timeout=30).json()
perps=[s['symbol'] for s in info['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL']
CORE=['BTCUSDT','ETHUSDT','SOLUSDT'];STABLE={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT'}
t7=int(dt.datetime(2026,7,1,tzinfo=dt.timezone.utc).timestamp()*1000)
vol={}
for s in perps:
    if s in CORE or s in STABLE: continue
    r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=t7,endTime=T1-1,limit=100),timeout=30).json()
    if isinstance(r,list) and len(r)>=90: vol[s]=sum(float(k[7]) for k in r)
    time.sleep(0.03)
UNI=CORE+sorted(vol,key=vol.get,reverse=True)[:7]
print('종목:',UNI)
days=[dt.date(2026,7,1)+dt.timedelta(i) for i in range(92)]
ev=[]
for s in UNI:
    h=kl(s,'1h');px={int(k[0]):float(k[1]) for k in h}
    fr={};[fr.__setitem__(int(x['fundingTime'])//3600000*3600000,float(x['fundingRate'])) for x in fund(s)]
    def p(d): return px.get(int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000))
    for d in days:
        t=int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000)
        hist=[p(d-dt.timedelta(i)) for i in range(1,51)]
        if None in hist or p(d) is None or p(d+dt.timedelta(1)) is None: continue
        ma50=np.mean(hist)
        if not (p(d)>ma50): continue
        r24=p(d)/p(d-dt.timedelta(1))-1
        if r24>-0.03: continue
        r=p(d+dt.timedelta(1))/p(d)-1;f=sum(v for k,v in fr.items() if t<=k<t+86400000)
        ev.append((d,s,r-f-0.0012))
print('종목:',UNI)
x=np.array([e[2] for e in ev]);n=len(x);print('건수',n)
if n:
    dd=np.array([e[0].toordinal() for e in ev]);ks=np.unique(dd);g={k:x[dd==k] for k in ks};rng=np.random.default_rng(20261001)
    ms=[np.concatenate([g[k] for k in rng.choice(ks,len(ks))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    mid=dt.date(2026,8,16).toordinal();a=x[dd<mid];b=x[dd>=mid]
    print(f'평균 {x.mean()*100:+.3f}% 중앙 {np.median(x)*100:+.3f}% 승률 {(x>0).mean()*100:.0f}% CI [{lo*100:+.3f},{hi*100:+.3f}] 최대 {x.max()*100:+.1f}% 최소 {x.min()*100:+.1f}%')
    print(f'전반 n={len(a)} {a.mean()*100 if len(a) else float("nan"):+.3f}%  후반 n={len(b)} {b.mean()*100 if len(b) else float("nan"):+.3f}%')
    for s in UNI:
        v=[e[2] for e in ev if e[1]==s]
        if v: print(f'  {s}: n={len(v)} {np.mean(v)*100:+.3f}%')
    print('판정:','판별 불가' if n<30 else ('성립' if x.mean()>0 and lo>0 and len(a) and len(b) and a.mean()>0 and b.mean()>0 else '기각'))
