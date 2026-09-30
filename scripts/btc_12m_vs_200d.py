"""prereg #16 PREREG_BTC_12M_VS_200D.md"""
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
kl=pull('/fapi/v1/klines',{'symbol':'BTCUSDT','interval':'1d'},lambda x:x[0])
fr=pull('/fapi/v1/fundingRate',{'symbol':'BTCUSDT'},lambda x:x['fundingTime'])
day=lambda ms: dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).date()
D=[day(k[0]) for k in kl];C=np.array([float(k[4]) for k in kl]);n=len(C)
fd={}
for x in fr: fd[day(x['fundingTime'])]=fd.get(day(x['fundingTime']),0)+float(x['fundingRate'])
F_=np.array([fd.get(d,0.0) for d in D])
ma=np.full(n,np.nan)
for i in range(199,n): ma[i]=C[i-199:i+1].mean()
st=np.zeros(n);cur=0
for i in range(199,n):
    cur=1 if C[i]>ma[i]*1.01 else (0 if C[i]<ma[i]*0.99 else cur); st[i]=cur
stB=np.zeros(n)
for i in range(365,n): stB[i]=1.0 if C[i]/C[i-365]-1>0 else 0.0
ret=np.r_[0,C[1:]/C[:-1]-1]
def net(st):
    p=np.r_[0,st[:-1]];return p*ret-np.r_[0,np.abs(np.diff(p))]*0.001-p*F_,p
a,pa=net(st);b,pb=net(stB)
s0=[i for i,d in enumerate(D) if d>=dt.date(2020,9,10)][0]
a,b,pa,pb=a[s0:],b[s0:],pa[s0:],pb[s0:];dd=D[s0:]
diff=b-a;m=len(diff)
rng=np.random.default_rng(20260930);L=30;nb=int(np.ceil(m/L));ms=[]
for _ in range(4000):
    st_=rng.integers(0,m-L+1,nb);ms.append(np.concatenate([diff[x:x+L] for x in st_])[:m].mean())
lo,hi=np.percentile(ms,[2.5,97.5])
def stats(x):
    e=np.cumprod(1+x);return e[-1],(e/np.maximum.accumulate(e)-1).min()
for nm,x in (('A 200일',a),('B 12M부호',b)):
    e,mdd=stats(x);print(f'{nm}: 누적 {e:.2f}배 MDD {mdd*100:.0f}%')
print(f'일평균 차이(B-A) {diff.mean()*100:+.4f}%  95% CI [{lo*100:+.4f},{hi*100:+.4f}]  다른 포지션 일수 {(pa!=pb).sum()}/{m}')
for y in sorted(set(d.year for d in dd)):
    mk=np.array([d.year==y for d in dd]);print(f' {y}: A {np.prod(1+a[mk])-1:+.0%}  B {np.prod(1+b[mk])-1:+.0%}')
print('판정:','B 채택 후보' if diff.mean()>0 and lo>0 else '판별 불가')
