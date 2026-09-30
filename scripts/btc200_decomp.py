"""BTC 200일 규칙 검증(기술): 연도별 분해, 최고 연도 제외, 펀딩 반영. 새 가설 아님 — core_lev 근거 점검."""
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
pos=np.r_[0,st[:-1]];ret=np.r_[0,C[1:]/C[:-1]-1];cost=np.r_[0,np.abs(np.diff(pos))]*0.001
for lev in (1,2):
    gross=lev*pos*ret-cost*lev; net=gross-lev*pos*F_    # 롱은 펀딩을 내는 쪽(양수 펀딩=지급)
    print(f'--- {lev}배 (펀딩 반영, 명목가/자본 기준) 총 펀딩 부담 연평균 {(lev*pos*F_)[199:].sum()/((n-199)/365)*100:.1f}%p')
    print(' 연도   규칙   보유(BTC)   규칙(펀딩전)')
    ys=sorted(set(d.year for d in D[199:]));res={}
    for y in ys:
        m=np.array([d.year==y for d in D])&(np.arange(n)>=199)
        res[y]=(np.prod(1+net[m])-1,np.prod(1+ret[m]*lev)-1,np.prod(1+gross[m])-1)
        print(f' {y}  {res[y][0]*100:+7.0f}%  {res[y][1]*100:+7.0f}%   {res[y][2]*100:+7.0f}%')
    tot=np.prod([1+v[0] for v in res.values()]);best=max(res,key=lambda y:res[y][0])
    print(f' 전체 {tot:.1f}배, 최고연도 {best} 제외 {np.prod([1+v[0] for y,v in res.items() if y!=best]):.2f}배')
    e=np.cumprod(1+net)[199:];print(f' MDD {(e/np.maximum.accumulate(e)-1).min()*100:.0f}%')
