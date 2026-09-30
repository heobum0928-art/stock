"""prereg #19 PREREG_TREND200_ETH_SOL.md"""
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
res={};btcD,btcr,_=run('BTCUSDT')
for sym in ('ETHUSDT','SOLUSDT'):
    D,r,h=run(sym);D=D[199:];yrs=len(r)/365
    a=st_(r,yrs);b=st_(h,yrs);res[sym]=a[3]>b[3]
    print(f'{sym} {D[0]}~{D[-1]}: 규칙 누적 {a[0]:.2f}배 연 {a[1]:+.0%} MDD {a[2]:.0%} 칼마 {a[3]:.2f} | 보유 누적 {b[0]:.2f}배 연 {b[1]:+.0%} MDD {b[2]:.0%} 칼마 {b[3]:.2f}')
    ys={}
    for d,x,y in zip(D,r,h): ys.setdefault(d.year,[[],[]]);ys[d.year][0].append(x);ys[d.year][1].append(y)
    print('  연도별(규칙/보유):',' '.join(f'{y}:{np.prod(1+np.array(v[0]))-1:+.0%}/{np.prod(1+np.array(v[1]))-1:+.0%}' for y,v in ys.items()))
    prod=lambda ex:np.prod([np.prod(1+np.array(v[0])) for y,v in ys.items() if y!=ex])
    best=max(ys,key=lambda y:np.prod(1+np.array(ys[y][0])));print(f'  최고연도 {best} 제외 규칙 누적 {prod(best):.2f}배')
    m=min(len(r),len(btcr));bd={d:x for d,x in zip(btcD[199:],btcr)};c=[(x,bd[d]) for d,x in zip(D,r) if d in bd]
    print(f'  BTC 규칙과 일수익 상관 {np.corrcoef(np.array(c).T)[0,1]:.2f}')
print('판정:','성립' if all(res.values()) else '기각',res)
