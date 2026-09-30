"""BTC 200일 규칙(PREREG_TREND_UPGRADE 기준선과 동일 규칙) 레버리지별 낙폭·청산 여유. 판정 아님, 요약용."""
import requests, datetime as dt, numpy as np
kl=[];s=int(dt.datetime(2019,9,10).timestamp()*1000)
while True:
    r=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol='BTCUSDT',interval='1d',startTime=s,limit=1500),timeout=30).json()
    if not r: break
    kl+=r; s=r[-1][0]+1
    if len(r)<1500: break
D=[dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date() for k in kl]
H=np.array([float(k[2]) for k in kl]);L=np.array([float(k[3]) for k in kl]);C=np.array([float(k[4]) for k in kl])
n=len(C);ma=np.full(n,np.nan)
for i in range(199,n): ma[i]=C[i-199:i+1].mean()
st=np.zeros(n);cur=0
for i in range(199,n):
    cur=1 if C[i]>ma[i]*1.01 else (0 if C[i]<ma[i]*0.99 else cur); st[i]=cur   # 종가에서 판단
pos=np.r_[0,st[:-1]]                       # 다음 날부터 적용
ret=np.r_[0,C[1:]/C[:-1]-1]
# 진입가 대비 일중 최대 역행(포지션 보유 중)
worst_adv=0;entry=None
for i in range(1,n):
    if pos[i]==1 and (pos[i-1]==0): entry=C[i-1]
    if pos[i]==1 and entry: worst_adv=min(worst_adv,L[i]/entry-1)
    if pos[i]==0: entry=None
print(f'{D[199]}~{D[-1]}  일수 {n-199}  ON 비율 {pos[199:].mean()*100:.0f}%  진입 후 일중 최대 역행 {worst_adv*100:.1f}%(명목가, 진입가 대비)')
for lev in (1,1.5,2):
    x=pos*ret*lev; eq=np.cumprod(1+x-np.r_[0,np.abs(np.diff(pos))]*0.001*lev)
    e=eq[199:]; mdd=(e/np.maximum.accumulate(e)-1).min()
    yrs=(n-199)/365; print(f'{lev}배: 누적 {e[-1]/e[0]:.1f}배 연 {(e[-1]/e[0])**(1/yrs)-1:+.0%} MDD {mdd:.0%}  (증거금 500 기준 낙폭 {mdd*500:+.0f} USDT)')
print('2배 청산가: 진입가 대비 약 -50% (유지증거금 무시한 근사). 위 최대 역행이 이보다 얕으면 청산 없음.')
