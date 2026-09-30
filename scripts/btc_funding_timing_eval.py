"""prereg #9 PREREG_BTC_FUNDING_TIMING.md"""
import requests, datetime as dt, numpy as np
from scipy.stats import spearmanr
F='https://fapi.binance.com'
def pull(path,params,key,step_field):
    out=[];start=int(dt.datetime(2019,9,1).timestamp()*1000)
    while True:
        r=requests.get(F+path,params=dict(params,startTime=start,limit=1000),timeout=30).json()
        if not isinstance(r,list) or not r: break
        out+=r; start=(r[-1][step_field] if isinstance(r[-1],dict) else r[-1][step_field])+1
        if len(r)<1000: break
    return out
fr=pull('/fapi/v1/fundingRate',{'symbol':'BTCUSDT'},None,'fundingTime')
kl=pull('/fapi/v1/klines',{'symbol':'BTCUSDT','interval':'1d'},None,0)
day=lambda ms: dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).date()
fund={};
for x in fr: fund.setdefault(day(x['fundingTime']),[]).append(float(x['fundingRate']))
px={day(k[0]):float(k[4]) for k in kl}
d=dt.date(2019,11,4)
while d.weekday()!=0: d+=dt.timedelta(1)
rows=[]
while d<=dt.date(2026,9,21):
    v=[x for i in range(1,8) for x in fund.get(d-dt.timedelta(i),[])]
    # 종가 기준: 월요일 00:00 UTC 시점 가격 = 전일(일요일) 종가
    p0=px.get(d-dt.timedelta(1)); p1=px.get(d+dt.timedelta(6))
    if len(v)>=18 and p0 and p1: rows.append((d,np.mean(v),p1/p0-1))
    d+=dt.timedelta(7)
Fv=np.array([r[1] for r in rows]);R=np.array([r[2] for r in rows]);n=len(rows)
r,p=spearmanr(Fv,R); print(f'n={n} rho={r:.3f} one-sided(p<0 dir)={p/2 if r<0 else 1-p/2:.4f}')
h=n//2
for lab,sl in [('first',slice(0,h)),('second',slice(h,n))]: print(lab,f'rho={spearmanr(Fv[sl],R[sl])[0]:.3f}')
q=np.quantile(Fv,[.2,.8]);hi=Fv>=q[1];lo=Fv<=q[0]
print(f'top20% R={R[hi].mean()*100:+.2f}%/wk n={hi.sum()}  bottom20% R={R[lo].mean()*100:+.2f}%/wk n={lo.sum()}  all={R.mean()*100:+.2f}%')
print('always-long x',np.prod(1+R).round(2),' skip-top20% x',np.prod(1+R*(~hi)).round(2))
