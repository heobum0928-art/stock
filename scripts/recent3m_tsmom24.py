"""prereg #22 PREREG_RECENT3M_TSMOM24.md"""
import requests, datetime as dt, numpy as np, time
F='https://fapi.binance.com'
T0=int(dt.datetime(2026,6,30,tzinfo=dt.timezone.utc).timestamp()*1000); T1=int(dt.datetime(2026,10,1,tzinfo=dt.timezone.utc).timestamp()*1000)
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
R={};L={};S={}
for s in UNI:
    h=kl(s,'1h');px={int(k[0]):float(k[1]) for k in h}  # 시가
    fr={};[fr.__setitem__(int(x['fundingTime'])//3600000*3600000,float(x['fundingRate'])) for x in fund(s)]
    prev=0;rows=[]
    for d in days:
        t=int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000);t_1=t-86400000;t1=t+86400000
        if t not in px or t_1 not in px or t1 not in px: rows.append((0,0,0));continue
        sig=1 if px[t]>px[t_1] else (-1 if px[t]<px[t_1] else 0)
        r=px[t1]/px[t]-1; f=sum(v for k,v in fr.items() if t<=k<t1)
        net=sig*r-sig*f-(0.0012 if sig!=prev and sig!=0 else 0)
        rows.append((net,sig,r));prev=sig
    S[s]=rows
port=np.array([np.mean([S[s][i][0] for s in UNI]) for i in range(92)])
rng=np.random.default_rng(20261001);ms=[port[rng.integers(0,92,92)].mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
e=np.cumprod(1+port);mdd=(e/np.maximum.accumulate(e)-1).min();h1=port[:46].mean();h2=port[46:].mean()
print(f'일평균 {port.mean()*100:+.3f}% CI [{lo*100:+.3f},{hi*100:+.3f}] 누적 {e[-1]:.3f}배 MDD {mdd:.1%} 전반 {h1*100:+.3f}% 후반 {h2*100:+.3f}%')
for s in UNI: print(f'  {s}: 기여 {np.mean([x[0] for x in S[s]])*100:+.3f}%/일')
lg=np.mean([np.mean([x[0] for x in S[s] if x[1]==1] or [0]) for s in UNI]);sh=np.mean([np.mean([x[0] for x in S[s] if x[1]==-1] or [0]) for s in UNI])
print(f'  롱 건당 {lg*100:+.3f}%  숏 건당 {sh*100:+.3f}%')
print('판정:','성립' if port.mean()>0 and lo>0 and h1>0 and h2>0 else '기각')
