"""prereg #27 PREREG_ALT_STRONG200.md"""
import requests, datetime as dt, numpy as np, time, json, os
F='https://fapi.binance.com'
C='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/alt/'
os.makedirs(C,exist_ok=True)
info=requests.get(F+'/fapi/v1/exchangeInfo',timeout=30).json()
perps=[s['symbol'] for s in info['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL']
EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT','BTCUSDT','ETHUSDT'}
def daily(s):
    p=C+s+'.json'
    if os.path.exists(p): return json.load(open(p))
    out=[];st=int(dt.datetime(2023,6,1,tzinfo=dt.timezone.utc).timestamp()*1000)
    while True:
        r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=st,limit=1500),timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=[(k[0],float(k[4]),float(k[7])) for k in r];st=r[-1][0]+1
        if len(r)<1500: break
    json.dump(out,open(p,'w'));time.sleep(0.04);return out
DAY={}
for s in perps:
    if s in EX: continue
    v=daily(s)
    if len(v)>260: DAY[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(k[1],k[2]) for k in v}
BTC={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():k[1] for k in daily('BTCUSDT')}
print(len(DAY),'종목')
days=[dt.date(2025,1,1)+dt.timedelta(i) for i in range((dt.date(2026,10,1)-dt.date(2025,1,1)).days+1)]
state={s:0 for s in DAY};held=set();rule=[];nsw=0;cnt=[]
for d in days:
    vols={}
    for s,v in DAY.items():
        w=[v.get(d-dt.timedelta(i)) for i in range(1,31)]
        if all(w) and all(v.get(d-dt.timedelta(i)) for i in range(1,201)) and v.get(d-dt.timedelta(91)): vols[s]=sum(x[1] for x in w)
    uni=sorted(vols,key=vols.get,reverse=True)[:20]
    b1=BTC[d-dt.timedelta(1)];b91=BTC[d-dt.timedelta(91)]
    rs={s:(DAY[s][d-dt.timedelta(1)][0]/DAY[s][d-dt.timedelta(91)][0]-1)-(b1/b91-1) for s in uni}
    top=sorted(uni,key=rs.get,reverse=True)[:5]
    new=set();rr=0
    for s in top:
        v=DAY[s];ma=np.mean([v[d-dt.timedelta(i)][0] for i in range(1,201)]);c1=v[d-dt.timedelta(1)][0]
        st=1 if c1>ma*1.01 else (0 if c1<ma*0.99 else state[s]);state[s]=st
        if st and d in v and d-dt.timedelta(1) in v:
            rr+=(v[d][0]/v[d-dt.timedelta(1)][0]-1-0.0003)/5;new.add(s)
    for s in uni:
        if s not in top: state[s]=0
    sw=len(new^held);rr-=0.001*sw/5;nsw+=sw;held=new;rule.append(rr);cnt.append(len(new))
def stat(x):
    e=np.cumprod(1+np.array(x));yrs=len(x)/365;mdd=(e/np.maximum.accumulate(e)-1).min();cagr=e[-1]**(1/yrs)-1;return e[-1],cagr,mdd,cagr/abs(mdd) if mdd else 0
a=stat(rule)
print(f'규칙: 누적 {a[0]:.2f}배 연 {a[1]:+.0%} MDD {a[2]:.0%} 칼마 {a[3]:.2f}  평균 보유 {np.mean(cnt):.1f}/5  전환 {nsw}')
for q in range(0,len(days),91):
    print(f'  {days[q]}~: {np.prod(1+np.array(rule[q:q+91]))-1:+.0%}')
print('판정:','성립' if a[0]>1 and a[2]>-0.4 else '기각')
