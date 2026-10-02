"""prereg #25 PREREG_TREND200_BAND5.md"""
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
def run(sym,band):
    D,C,F_=series(sym);n=len(C);ma=np.full(n,np.nan)
    for i in range(199,n): ma[i]=C[i-199:i+1].mean()
    st=np.zeros(n);cur=0
    for i in range(199,n):
        cur=1 if C[i]>ma[i]*(1+band) else (0 if C[i]<ma[i]*(1-band) else cur); st[i]=cur
    pos=np.r_[0,st[:-1]];ret=np.r_[0,C[1:]/C[:-1]-1]
    return D[199:],(pos*ret-np.r_[0,np.abs(np.diff(pos))]*0.001-pos*F_)[199:],pos[199:]
def st_(x,yrs):
    e=np.cumprod(1+x);mdd=(e/np.maximum.accumulate(e)-1).min();cagr=e[-1]**(1/yrs)-1;return e[-1],cagr,mdd,cagr/abs(mdd)
RA={};RB={};PA={};PB={}
for sym in ('BTCUSDT','ETHUSDT','SOLUSDT'):
    D,a,pa=run(sym,0.01);_,b,pb=run(sym,0.05)
    RA[sym]={d:x for d,x in zip(D,a)};RB[sym]={d:x for d,x in zip(D,b)};PA[sym]=dict(zip(D,pa));PB[sym]=dict(zip(D,pb))
common=sorted(set.intersection(*[set(v) for v in RA.values()]));common=[d for d in common if d>=dt.date(2021,4,1)]
a=np.mean([[RA[s][d] for d in common] for s in RA],axis=0);b=np.mean([[RB[s][d] for d in common] for s in RB],axis=0)
diff=b-a;m=len(diff);rng=np.random.default_rng(20261002);L=30;nb=int(np.ceil(m/L));ms=[]
for _ in range(4000):
    st_=rng.integers(0,m-L+1,nb);ms.append(np.concatenate([diff[x:x+L] for x in st_])[:m].mean())
lo,hi=np.percentile(ms,[2.5,97.5]);yrs=m/365
for nm,x in (('A ±1%',a),('B ±5%',b)):
    e=np.cumprod(1+x);print(f'{nm}: 누적 {e[-1]:.2f}배 연 {e[-1]**(1/yrs)-1:+.0%} MDD {(e/np.maximum.accumulate(e)-1).min():.0%}')
for nm,P in (('A',PA),('B',PB)):
    print(nm,'전환 횟수',sum(sum(1 for i in range(1,len(common)) if P[s][common[i]]!=P[s][common[i-1]]) for s in P))
diffdays=sum(1 for d in common for s in PA if PA[s][d]!=PB[s][d])
print(f'일평균 차이 {diff.mean()*100:+.4f}% CI [{lo*100:+.4f},{hi*100:+.4f}] 다른 포지션 일수(종목합) {diffdays}')
for y in sorted(set(d.year for d in common)):
    mk=np.array([d.year==y for d in common]);print(f' {y}: A {np.prod(1+a[mk])-1:+.0%} B {np.prod(1+b[mk])-1:+.0%}')
print('판정:','B 채택 후보' if diff.mean()>0 and lo>0 else '판별 불가')
