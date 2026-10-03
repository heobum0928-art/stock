"""기술: 실거래 숏 원장을 진입 전 30일 수익률로 가른다. 사전 선언한 분할 하나: 30일 수익률 > +50% 여부."""
import pandas as pd,numpy as np,requests,datetime as dt,time
d=pd.concat([pd.read_csv('data/margin_short_wide_ledger.csv'),pd.read_csv('data/margin_short_ledger.csv')])
d['t']=pd.to_datetime(d['entry_time'],utc=True,format='mixed')
cache={}
def k(sym):
    if sym in cache: return cache[sym]
    r=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol=sym,interval='1d',startTime=int(dt.datetime(2026,5,1,tzinfo=dt.timezone.utc).timestamp()*1000),limit=300),timeout=30).json()
    cache[sym]={dt.datetime.fromtimestamp(x[0]/1000,dt.timezone.utc).date():float(x[4]) for x in r} if isinstance(r,list) else {}
    time.sleep(0.05);return cache[sym]
r30=[]
for _,r in d.iterrows():
    v=k(r.symbol);e=r.t.date();a=v.get(e-dt.timedelta(1));b=v.get(e-dt.timedelta(31))
    r30.append(a/b-1 if a and b else np.nan)
d['r30']=r30;x=d.dropna(subset=['r30'])
print(f'30일 수익률 확보 {len(x)}/{len(d)}건')
for nm,m in (('30일 +50% 초과',x.r30>0.5),('30일 +50% 이하',x.r30<=0.5)):
    s=x[m];print(f'{nm}: n={len(s)} 합계 {s.net_pnl_usdt.sum():+.1f} USDT 건당 평균 {s.net_pnl_pct_margin.mean():+.1f}%(증거금) 중앙 {s.net_pnl_pct_margin.median():+.1f}% 승률 {(s.net_pnl_usdt>0).mean()*100:.0f}% 최악 {s.net_pnl_pct_margin.min():+.0f}%')
for lo,hi in ((-9,0),(0,0.5),(0.5,1.5),(1.5,99)):
    s=x[(x.r30>lo)&(x.r30<=hi)];print(f'  참고 r30 {lo:+.1f}~{hi:+.1f}: n={len(s)} 합계 {s.net_pnl_usdt.sum():+.1f} 평균 {s.net_pnl_pct_margin.mean() if len(s) else float("nan"):+.1f}%')
