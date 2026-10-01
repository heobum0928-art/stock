"""기술(판정 아님): BTC·ETH·SOL 200일 규칙 균등 포트폴리오의 레버리지별 성장률 — 수익 극대화 관점.
종목별 격리증거금 가정: 보유 중 일중 저가가 진입가 대비 -1/레버리지(유지증거금 0.5% 차감) 이하로 가면 그 1/3 몫은 0(청산)."""
import requests, datetime as dt, numpy as np
F='https://fapi.binance.com'
def pull(path,params,f,lim):
    out=[];s=int(dt.datetime(2019,9,10).timestamp()*1000)
    while True:
        r=requests.get(F+path,params=dict(params,startTime=s,limit=lim),timeout=30).json()
        if not r: break
        out+=r; s=f(r[-1])+1
        if len(r)<lim: break
    return out
day=lambda ms: dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).date()
def load(sym):
    kl=pull('/fapi/v1/klines',{'symbol':sym,'interval':'1d'},lambda x:x[0],1500)
    fr=pull('/fapi/v1/fundingRate',{'symbol':sym},lambda x:x['fundingTime'],1000)
    fd={}
    for x in fr: fd[day(x['fundingTime'])]=fd.get(day(x['fundingTime']),0)+float(x['fundingRate'])
    D=[day(k[0]) for k in kl];C=np.array([float(k[4]) for k in kl]);L=np.array([float(k[3]) for k in kl])
    n=len(C);ma=np.full(n,np.nan)
    for i in range(199,n): ma[i]=C[i-199:i+1].mean()
    st=np.zeros(n);cur=0
    for i in range(199,n): cur=1 if C[i]>ma[i]*1.01 else (0 if C[i]<ma[i]*0.99 else cur); st[i]=cur
    pos=np.r_[0,st[:-1]]
    return {d:(pos[i],C[i]/C[i-1]-1 if i else 0,L[i]/C[i-1]-1 if i else 0,fd.get(d,0.0),abs(pos[i]-pos[i-1]) if i else 0) for i,d in enumerate(D) if i>=200}
S={s:load(s) for s in ('BTCUSDT','ETHUSDT','SOLUSDT')}
days=sorted(d for d in set.intersection(*[set(v) for v in S.values()]) if d>=dt.date(2021,4,1))
print(f'{days[0]}~{days[-1]}')
# 모델: 종목별 몫(1/3)에 매일 같은 레버리지를 다시 맞춘다(고정 레버리지). 하루 저가 역행 × 레버리지가 -99.5% 이하면 그 몫은 청산(0).
for lev in (1,1.5,2,3):
    sleeve={s:1/3 for s in S};peak=1;mdd=0;liq=0
    for d in days:
        for s in S:
            p,r,lo,f,ch=S[s][d]
            if ch: sleeve[s]*=1-0.001*lev
            if p and sleeve[s]>0:
                if lev*lo<=-0.995: sleeve[s]=0;liq+=1;continue
                sleeve[s]*=1+lev*r-lev*f
        eq=sum(sleeve.values())
        if d.month==1 and d.day==1: sleeve={s:eq/3 for s in S}
        peak=max(peak,eq);mdd=min(mdd,eq/peak-1)
    yrs=len(days)/365
    print(f'{lev}배: 누적 {eq:.2f}배 연복리 {eq**(1/yrs)-1:+.0%} 최대낙폭 {mdd:.0%} 청산 {liq}회')
print('보유 중 하루 저가 역행 상위:')
ev=sorted(((S[s][d][2],s,d) for s in S for d in days if S[s][d][0]),key=lambda x:x[0])[:5]
for lo,s,d in ev: print(f'  {d} {s} 일중 저가 {lo:+.1%}')
