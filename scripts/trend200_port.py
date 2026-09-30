"""prereg #20 PREREG_TREND200_PORT.md"""
import requests, datetime as dt, numpy as np
F='https://fapi.binance.com'
def pull(path,params,f):
    out=[];s=int(dt.datetime(2019,9,10).timestamp()*1000)
    while True:
        r=requests.get(F+path,params=dict(params,startTime=s,limit=1500 if 'klines' in path else 1000),timeout=30).json()
        if not r: break
        out+=r; s=f(r[-1])+1
        if len(r)<(1500 if 'klines' in path else 1000): break
    return out
def series(sym):
    kl=pull('/fapi/v1/klines',{'symbol':sym,'interval':'1d'},lambda x:x[0])
    fr=pull('/fapi/v1/fundingRate',{'symbol':sym},lambda x:x['fundingTime'])
    day=lambda ms: dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).date()
    D=[day(k[0]) for k in kl];C=np.array([float(k[4]) for k in kl]);fd={}
    for x in fr: fd[day(x['fundingTime'])]=fd.get(day(x['fundingTime']),0)+float(x['fundingRate'])
    return D,C,np.array([fd.get(d,0.0) for d in D])
def run(sym):
    D,C,F_=series(sym);n=len(C);ma=np.full(n,np.nan)
    for i in range(199,n): ma[i]=C[i-199:i+1].mean()
    st=np.zeros(n);cur=0
    for i in range(199,n):
        cur=1 if C[i]>ma[i]*1.01 else (0 if C[i]<ma[i]*0.99 else cur); st[i]=cur
    pos=np.r_[0,st[:-1]];ret=np.r_[0,C[1:]/C[:-1]-1]
    rule=pos*ret-np.r_[0,np.abs(np.diff(pos))]*0.001-pos*F_;hold=ret-F_
    return D,rule[199:],hold[199:]
def st_(x,yrs):
    e=np.cumprod(1+x);mdd=(e/np.maximum.accumulate(e)-1).min();cagr=e[-1]**(1/yrs)-1;return e[-1],cagr,mdd,cagr/abs(mdd)
R={}
for sym in ('BTCUSDT','ETHUSDT','SOLUSDT'):
    D,r,h=run(sym);R[sym]={d:(x,y) for d,x,y in zip(D[199:],r,h)}
common=sorted(set.intersection(*[set(v) for v in R.values()]));common=[d for d in common if d>=dt.date(2021,4,1)]
btc=np.array([R['BTCUSDT'][d][0] for d in common])
port=np.mean([[R[s][d][0] for d in common] for s in R],axis=0)
hold=np.mean([[R[s][d][1] for d in common] for s in R],axis=0)
yrs=len(common)/365
rows={'BTC 규칙 단독':btc,'3자산 규칙 균등':port,'3자산 균등 보유':hold}
S={k:st_(v,yrs) for k,v in rows.items()}
print(f'{common[0]}~{common[-1]}')
for k,a in S.items(): print(f'{k}: 누적 {a[0]:.2f}배 연 {a[1]:+.0%} MDD {a[2]:.0%} 칼마 {a[3]:.2f}')
for k,v in rows.items():
    ys={}
    for d,x in zip(common,v): ys.setdefault(d.year,[]).append(x)
    yy={y:np.prod(1+np.array(z))-1 for y,z in ys.items()};best=max(yy,key=yy.get)
    print(f'  {k} 연도별:',' '.join(f'{y}:{v_:+.0%}' for y,v_ in yy.items()),f'| 최고연도 {best} 제외 누적 {np.prod([1+v_ for y,v_ in yy.items() if y!=best]):.2f}배')
ok=S['3자산 규칙 균등'][3]>S['BTC 규칙 단독'][3] and S['3자산 규칙 균등'][2]>S['BTC 규칙 단독'][2]
print('판정:','성립' if ok else '기각')
