"""prereg #39 (기간 C 이벤트 추출)"""
import requests, datetime as dt, numpy as np, time, json, os
F='https://fapi.binance.com'
A='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/altC/'
H='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/nr7hC/'
os.makedirs(H,exist_ok=True)
EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT','BTCUSDT','ETHUSDT'}
def dayk(s):
    p=A+s+'.json'
    if os.path.exists(p): return json.load(open(p))
    out=[];st=int(dt.datetime(2023,6,1,tzinfo=dt.timezone.utc).timestamp()*1000)
    while True:
        r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=st,limit=1500),timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=[(k[0],float(k[4]),float(k[7])) for k in r];st=r[-1][0]+1
        if len(r)<1500: break
    json.dump(out,open(p,'w'));return out
def full(s):  # 일봉 OHLC
    p=H+'d_'+s+'.json'
    if os.path.exists(p): return json.load(open(p))
    out=[];st=int(dt.datetime(2020,10,1,tzinfo=dt.timezone.utc).timestamp()*1000)
    while True:
        r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=st,limit=1500),timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=[(k[0],float(k[1]),float(k[2]),float(k[3]),float(k[4]),float(k[7])) for k in r];st=r[-1][0]+1
        if len(r)<1500: break
    json.dump(out,open(p,'w'));time.sleep(0.04);return out
info=requests.get(F+'/fapi/v1/exchangeInfo',timeout=30).json()
perps=[s['symbol'] for s in info['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL' and s['symbol'] not in EX]
DAY={}
for s in perps:
    v=full(s)
    if len(v)>40: DAY[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():k for k in v}
print(len(DAY),'종목')
def hourly(s,d):
    p=H+f'{s}_{d}.json'
    if os.path.exists(p): return json.load(open(p))
    t=int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000)
    r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1h',startTime=t,endTime=t+86399999,limit=24),timeout=30).json()
    out=[(float(k[2]),float(k[3]),float(k[4])) for k in r] if isinstance(r,list) else []
    json.dump(out,open(p,'w'));time.sleep(0.03);return out
ev=[]
for d in [dt.date(2021,3,1)+dt.timedelta(i) for i in range((dt.date(2022,12,31)-dt.date(2021,3,1)).days+1)]:
    vols={}
    for s,v in DAY.items():
        w=[v.get(d-dt.timedelta(i)) for i in range(1,31)]
        if all(w): vols[s]=sum(x[5] for x in w)
    for s in sorted(vols,key=vols.get,reverse=True)[:20]:
        v=DAY[s];rg=[(v[d-dt.timedelta(i)][2]-v[d-dt.timedelta(i)][3])/v[d-dt.timedelta(i)][4] for i in range(1,8)]
        if rg[0]>min(rg): continue
        if rg[0]!=min(rg): continue
        hi=v[d-dt.timedelta(1)][2];lo=v[d-dt.timedelta(1)][3]
        hb=hourly(s,d)
        if len(hb)<20: continue
        side=None
        for (h,l,c) in hb:
            up=h>hi;dn=l<lo
            if up and dn: side='skip';break
            if up: side='L';break
            if dn: side='S';break
        if side in (None,'skip'): continue
        entry=hi if side=='L' else lo;stop=lo if side=='L' else hi
        started=False;after=[]
        for (h,l,c) in hb:
            if not started:
                if (side=='L' and h>hi) or (side=='S' and l<lo): started=True
                else: continue
            after.append((h,l,c))
        mx=max(a[0] for a in after);mn=min(a[1] for a in after);cl=hb[-1][2]
        # 손절 시점
        stopped=False;exitp=cl
        for (h,l,c) in after:
            if side=='L' and l<=stop: exitp=stop;stopped=True;break
            if side=='S' and h>=stop: exitp=stop;stopped=True;break
        adv=(entry-mn)/entry if side=='L' else (mx-entry)/entry
        # 손절 전까지의 불리 극단(손절 있는 변형의 청산 판정용)
        adv_stop=0.0;
        for (h,l,c) in after:
            a=(entry-l)/entry if side=='L' else (h-entry)/entry
            adv_stop=max(adv_stop,a)
            if (side=='L' and l<=stop) or (side=='S' and h>=stop): break
        rs=(exitp/entry-1) if side=='L' else (entry/exitp-1);rc=(cl/entry-1) if side=='L' else (entry/cl-1)
        ev.append((str(d),s,side,rs,rc,adv,adv_stop))
import json;json.dump(ev,open('C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/ext_C.json','w'));print('C 이벤트',len(ev))
sys_exit=True
