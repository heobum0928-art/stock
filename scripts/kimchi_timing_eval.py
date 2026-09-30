"""prereg #10 PREREG_KIMCHI_TIMING.md"""
import requests, datetime as dt, time, numpy as np
from scipy.stats import spearmanr
def upbit(market):
    out={};to=None
    while True:
        p={'market':market,'count':200}
        if to: p['to']=to
        r=requests.get('https://api.upbit.com/v1/candles/days',params=p,timeout=30).json()
        if not isinstance(r,list) or not r: break
        for c in r: out[dt.date.fromisoformat(c['candle_date_time_utc'][:10])]=c['trade_price']
        to=r[-1]['candle_date_time_utc']+'Z'; time.sleep(0.15)
        if len(r)<200: break
    return out
btck=upbit('KRW-BTC'); usdt=upbit('KRW-USDT')
kl=[];start=int(dt.datetime(2019,1,1).timestamp()*1000)
while True:
    r=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol='BTCUSDT',interval='1d',startTime=start,limit=1500),timeout=30).json()
    if not r: break
    kl+=r; start=r[-1][0]+1
    if len(r)<1500: break
bn={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():float(k[4]) for k in kl}
P={d:btck[d]/(bn[d]*usdt[d])-1 for d in btck if d in usdt and d in bn}
print('P days',len(P),min(P),max(P),f'mean={np.mean(list(P.values()))*100:.2f}%')
d=min(P)+dt.timedelta(7)
while d.weekday()!=0: d+=dt.timedelta(1)
rows=[]
while d<=dt.date(2026,9,21):
    v=[P[d-dt.timedelta(i)] for i in range(1,8) if d-dt.timedelta(i) in P]
    p0=bn.get(d-dt.timedelta(1));p1=bn.get(d+dt.timedelta(6))
    if len(v)>=6 and p0 and p1: rows.append((np.mean(v),p1/p0-1))
    d+=dt.timedelta(7)
F=np.array([r[0] for r in rows]);R=np.array([r[1] for r in rows]);n=len(rows)
r,p=spearmanr(F,R);print(f'n={n} rho={r:.3f} one-sided(rho>0)={p/2 if r>0 else 1-p/2:.4f}')
h=n//2
for lab,sl in [('first',slice(0,h)),('second',slice(h,n))]: print(lab,f'rho={spearmanr(F[sl],R[sl])[0]:.3f}')
q=np.quantile(F,[.2,.8]);hi=F>=q[1];lo=F<=q[0]
print(f'top20% R={R[hi].mean()*100:+.2f}%/wk n={hi.sum()} bottom20% R={R[lo].mean()*100:+.2f}%/wk n={lo.sum()} all={R.mean()*100:+.2f}%')
