"""prereg #54 PREREG_SPIKE_SLIP.md"""
import pandas as pd,numpy as np,requests,datetime as dt,time
from scipy.stats import spearmanr
t=pd.read_csv('data/margin_short_wide_trades.csv');t=t[t['live']==True].copy()
t['a']=pd.to_datetime(t.entry_time,format='mixed',utc=True);t=t[t.a>='2026-09-23'].copy()
t['slip']=np.maximum(0,-t.pnl_pct-5.0)
sp=[]
for _,r in t.iterrows():
    e=int(r.a.timestamp()*1000)
    k=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol=r.symbol,interval='1m',startTime=e-60*60000,endTime=e-1,limit=60),timeout=20).json()
    v=[(float(x[2])-float(x[3]))/float(x[1])*100 for x in k if float(x[1])>0] if isinstance(k,list) else []
    sp.append(max(v) if len(v)>=30 else np.nan);time.sleep(0.05)
t['spike']=sp;t=t.dropna(subset=['spike']);n=len(t);print(f'대상 {n}건 (손절 {int((t.pnl_pct<=-4.5).sum())}건)')
rho,_=spearmanr(t.spike,t.slip)
rng=np.random.default_rng(20261009);cnt=0
for _ in range(10000):
    if spearmanr(t.spike.values,rng.permutation(t.slip.values))[0]>=rho: cnt+=1
p=(cnt+1)/10001
print(f'ρ(spike, slip) = {rho:+.3f}  단측 순열 p = {p:.4f}')
s=t[t.pnl_pct<=-4.5];print(f'손절 건만 ρ = {spearmanr(s.spike,s.slip)[0]:+.3f} (n={len(s)})')
q=t.spike.quantile(0.75);hi=t.spike>=q
print(f'spike 상위 25%(≥{q:.1f}%): n={hi.sum()} 평균 slip {t.slip[hi].mean():.2f} 최대 {t.slip[hi].max():.2f} 손절 비율 {np.mean(t.pnl_pct[hi]<=-4.5)*100:.0f}% | 나머지: n={(~hi).sum()} 평균 slip {t.slip[~hi].mean():.2f} 최대 {t.slip[~hi].max():.2f} 손절 비율 {np.mean(t.pnl_pct[~hi]<=-4.5)*100:.0f}%')
print('JCT/OGN spike:',t[t.symbol.isin(['JCTUSDT','OGNUSDT'])][['symbol','spike','slip']].round(2).to_string(index=False))
lost=t.pnl_usdt[hi].sum();print(f'참고: 상위 25% 건의 실제 손익 합계(2배 시절 환산 아님) {lost:+.1f} USDT, 전체 {t.pnl_usdt.sum():+.1f}')
print('판정:','판별 불가' if n<30 else ('성립' if rho>0 and p<0.05 else '기각'))
