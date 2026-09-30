"""prereg #8 PREREG_STABLE_FLOW.md"""
import requests, json, os, time, datetime as dt
import numpy as np
from scipy.stats import spearmanr
C='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
def cache(name, fn):
    p=C+name
    if os.path.exists(p): return json.load(open(p))
    d=fn(); json.dump(d,open(p,'w')); return d
st=cache('stable.json',lambda: requests.get('https://stablecoins.llama.fi/stablecoincharts/all',timeout=60).json())
sup={dt.date.fromtimestamp(int(r['date']),dt.timezone.utc) if False else dt.datetime.utcfromtimestamp(int(r['date'])).date(): r['totalCirculatingUSD']['peggedUSD'] for r in st}
F='https://fapi.binance.com'
info=cache('info.json',lambda: requests.get(F+'/fapi/v1/exchangeInfo',timeout=30).json())
syms=[s['symbol'] for s in info['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL']
EX={'BTCUSDT','ETHUSDT','USDCUSDT','FDUSDUSDT','BTCDOMUSDT'}
def kl(s):
    out=[];start=int(dt.datetime(2023,11,1).timestamp()*1000)
    while True:
        r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=start,limit=1500),timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=r
        if len(r)<1500: break
        start=r[-1][0]+1
    return {dt.datetime.utcfromtimestamp(x[0]/1000).date().isoformat():(float(x[4]),float(x[7])) for x in out}
K=cache('klines.json',lambda:{s:(time.sleep(0.05),kl(s))[1] for s in syms})
def px(s,d): return K[s].get(d.isoformat(),(None,None))[0]
rows=[]
d=dt.date(2024,1,1)
while d<=dt.date(2026,9,21):
    s0,s30=sup.get(d),sup.get(d-dt.timedelta(30))
    if s0 and s30:
        vol=[]
        for s in syms:
            if s in EX: continue
            v=[K[s].get((d-dt.timedelta(i)).isoformat(),(0,0))[1] for i in range(1,31)]
            if all(v) and px(s,d) and px(s,d+dt.timedelta(7)): vol.append((sum(v),s))
        top=[s for _,s in sorted(vol)[-30:]]
        alt=np.mean([px(s,d+dt.timedelta(7))/px(s,d)-1 for s in top])
        btc=px('BTCUSDT',d+dt.timedelta(7))/px('BTCUSDT',d)-1
        rows.append((d.isoformat(),s0/s30-1,alt-btc))
    d+=dt.timedelta(7)
S=np.array([r[1] for r in rows]);Y=np.array([r[2] for r in rows])
r,p=spearmanr(S,Y); print(f'n={len(rows)} rho={r:.3f} one-sided p={p/2 if r>0 else 1-p/2:.4f}')
for k in range(4):
    rk,_=spearmanr(S[k::4],Y[k::4]); print(f' thinned offset{k}: n={len(S[k::4])} rho={rk:.3f}')
for dd,s,y in rows:
    if dd.startswith('2025-08') or dd.startswith('2025-09'):
        print(dd,f'S={s*100:.2f}% pct={(S<s).mean()*100:.0f} Y={y*100:+.1f}%')
q=np.quantile(S,[1/3,2/3])
for lab,m in [('low',S<q[0]),('mid',(S>=q[0])&(S<q[1])),('high',S>=q[1])]: print(lab,m.sum(),f'{Y[m].mean()*100:+.2f}%/wk')
