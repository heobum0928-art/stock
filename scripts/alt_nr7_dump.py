"""prereg #28 PREREG_ALT_NR7.md"""
import requests, datetime as dt, numpy as np, time, json, os
F='https://fapi.binance.com'
A='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/alt/'
H='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/nr7h/'
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
    out=[];st=int(dt.datetime(2024,12,1,tzinfo=dt.timezone.utc).timestamp()*1000)
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
    if len(v)>200: DAY[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():k for k in v}
print(len(DAY),'종목')
def hourly(s,d):
    p=H+f'{s}_{d}.json'
    if os.path.exists(p): return json.load(open(p))
    t=int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000)
    r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1h',startTime=t,endTime=t+86399999,limit=24),timeout=30).json()
    out=[(float(k[2]),float(k[3]),float(k[4])) for k in r] if isinstance(r,list) else []
    json.dump(out,open(p,'w'));time.sleep(0.03);return out
ev=[]
for d in [dt.date(2025,1,1)+dt.timedelta(i) for i in range((dt.date(2026,10,1)-dt.date(2025,1,1)).days+1)]:
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
        # 진입 봉 이후 봉들로 손절 확인(진입 봉 자체는 안 봄 — 보수적이지 않음: 진입 봉 내 반대 터치 무시)
        started=False;exitp=hb[-1][2]
        for (h,l,c) in hb:
            if not started:
                if (side=='L' and h>hi) or (side=='S' and l<lo): started=True
                continue
            if side=='L' and l<=stop: exitp=stop;break
            if side=='S' and h>=stop: exitp=stop;break
        r=(exitp/entry-1) if side=='L' else (entry/exitp-1)
        ev.append((d,s,side,r-0.0012))
import json;json.dump([[str(e[0]),e[2],e[3]] for e in ev],open('C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/ev_cur.json','w'))
x=np.array([e[3] for e in ev]);n=len(x);print('건수',n)
if n:
    dd=np.array([e[0].toordinal() for e in ev]);ks=np.unique(dd);g={k:x[dd==k] for k in ks};rng=np.random.default_rng(20261002)
    ms=[np.concatenate([g[k] for k in rng.choice(ks,len(ks))]).mean() for _ in range(4000)];lo_,hi_=np.percentile(ms,[2.5,97.5])
    cut=dt.date(2026,1,1).toordinal();a=x[dd<cut];b=x[dd>=cut]
    print(f'평균 {x.mean()*100:+.3f}% 중앙 {np.median(x)*100:+.3f}% 승률 {(x>0).mean()*100:.0f}% CI [{lo_*100:+.3f},{hi_*100:+.3f}] 평균이익 {x[x>0].mean()*100:+.2f}% 평균손실 {x[x<=0].mean()*100:+.2f}% 최대 {x.max()*100:+.1f}% 최소 {x.min()*100:+.1f}%')
    print(f'전반 n={len(a)} {a.mean()*100:+.3f}% 후반 n={len(b)} {b.mean()*100:+.3f}%  상위10 이익비중 {np.sort(x)[::-1][:10].clip(0).sum()/x.clip(0).sum()*100:.0f}%')
    for sd in ('L','S'): m=np.array([e[2]==sd for e in ev]);print(f'  {sd}: n={m.sum()} {x[m].mean()*100:+.3f}%')
    print('판정:','판별 불가' if n<100 else ('성립' if x.mean()>0 and lo_>0 and a.mean()>0 and b.mean()>0 else '기각'))
