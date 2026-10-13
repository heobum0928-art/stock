"""기술: 오늘(UTC) 기준 알트 30일 국면 — #40 정의와 동일. 매매 판단 아님."""
import requests,datetime as dt,numpy as np,time
F='https://fapi.binance.com';EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT','BTCUSDT','ETHUSDT'}
today=dt.datetime.now(dt.timezone.utc).date()
ms=lambda d:int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000)
syms=[s['symbol'] for s in requests.get(F+'/fapi/v1/exchangeInfo',timeout=30).json()['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL' and s['symbol'] not in EX and s.get('status')=='TRADING']
D={}
for s in syms:
    r=requests.get(F+'/fapi/v1/klines',params=dict(symbol=s,interval='1d',startTime=ms(today-dt.timedelta(75)),endTime=ms(today)-1,limit=100),timeout=30).json()
    if isinstance(r,list) and r: D[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(float(k[4]),float(k[7])) for k in r}
    time.sleep(0.03)
def key_ret(d):
    vols={}
    for s,v in D.items():
        w=[v.get(d-dt.timedelta(i)) for i in range(1,31)]
        if all(w) and d in v and d+dt.timedelta(1) in v: vols[s]=sum(a[1] for a in w)
    top=sorted(vols,key=vols.get,reverse=True)[:20]
    return np.mean([D[s][d+dt.timedelta(1)][0]/D[s][d][0]-1 for s in top]) if len(top)>=10 else None
rs=[key_ret(today-dt.timedelta(i)) for i in range(1,31)]
print('계산일(UTC)',today,'/ 바구니 일수익 확보',sum(x is not None for x in rs),'/30')
if all(x is not None for x in rs):
    reg=np.prod([1+x for x in rs])-1
    print(f'알트 바구니 직전 30일 수익률 {reg*100:+.1f}%  →',"하락 국면(≤0): NR7 숏 가동" if reg<=0 else "상승 국면(>0): NR7 숏 쉬는 날")
    for k in (7,14): print(f'  참고 최근 {k}일 {np.prod([1+x for x in rs[:k]])*100-100:+.1f}%')
