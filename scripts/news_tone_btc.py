"""prereg #51 PREREG_NEWS_TONE_BTC.md"""
import glob,json,datetime as dt,numpy as np,requests
from scipy.stats import spearmanr
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/gdelt/'
tone={}
for f in sorted(glob.glob(S+'tone_*.json')):
    for p in json.load(open(f)):
        d=dt.datetime.strptime(p['date'][:8],'%Y%m%d').date();tone.setdefault(d,[]).append(float(p['value']))
tone={d:float(np.mean(v)) for d,v in tone.items()}
print(f'뉴스 분위기 일수 {len(tone)} ({min(tone)}~{max(tone)})')
kl=[];st=int(dt.datetime(2020,12,1,tzinfo=dt.timezone.utc).timestamp()*1000)
while True:
    r=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol='BTCUSDT',interval='1d',startTime=st,limit=1500),timeout=30).json()
    if not r: break
    kl+=r;st=r[-1][0]+1
    if len(r)<1500: break
C={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():float(k[4]) for k in kl}
days=sorted(d for d in tone if d>=dt.date(2021,1,1))
rows=[]
for d in days:
    past=[tone.get(d-dt.timedelta(i)) for i in range(1,31)]
    past=[x for x in past if x is not None]
    nxt=d+dt.timedelta(1)
    if len(past)<20 or d not in C or nxt not in C: continue
    z=(tone[d]-np.mean(past))/(np.std(past,ddof=1) or np.nan)
    if np.isnan(z): continue
    rows.append((d,z,C[nxt]/C[d]-1))
Z=np.array([r[1] for r in rows]);R=np.array([r[2] for r in rows]);D=[r[0] for r in rows];n=len(rows)
print(f'유효 일수 {n}')
rho,_=spearmanr(Z,R)
rng=np.random.default_rng(20261008);L=30;nb=int(np.ceil(n/L));ms=[]
for _ in range(2000):
    s=rng.integers(0,n-L+1,nb);idx=np.concatenate([np.arange(a,a+L) for a in s])[:n];ms.append(spearmanr(Z[idx],R[idx])[0])
lo,hi=np.percentile(ms,[2.5,97.5]);h=n//2
r1=spearmanr(Z[:h],R[:h])[0];r2=spearmanr(Z[h:],R[h:])[0]
print(f'풀링 ρ={rho:+.4f} 95% CI [{lo:+.4f},{hi:+.4f}]  전반 ρ={r1:+.4f} 후반 ρ={r2:+.4f}')
for y in sorted(set(d.year for d in D)):
    m=np.array([d.year==y for d in D]);print(f'  {y}: n={m.sum()} ρ={spearmanr(Z[m],R[m])[0]:+.3f}')
q=np.quantile(Z,[.2,.8]);hi_=Z>=q[1];lo_=Z<=q[0]
print(f'z 상위 20% 다음 날 평균 {R[hi_].mean()*100:+.3f}% (n={hi_.sum()}) vs 하위 20% {R[lo_].mean()*100:+.3f}% (n={lo_.sum()}) / 전체 {R.mean()*100:+.3f}%')
pos=np.where(Z>0,R-np.where(np.r_[0,np.diff((Z>0).astype(int))]!=0,0.001,0),0.0)
print(f'"z>0이면 롱·아니면 현금" 누적 {np.prod(1+pos):.2f}배 vs 단순 보유 {np.prod(1+R):.2f}배')
print('판정:','판별 불가' if n<1000 else ('성립' if rho>0 and lo>0 and r1>0 and r2>0 else '기각'))
