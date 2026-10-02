"""prereg #33 PREREG_NR7_REGIME.md"""
import json,requests,datetime as dt,numpy as np
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
kl=[];st=int(dt.datetime(2022,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)
while True:
    r=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol='BTCUSDT',interval='1d',startTime=st,limit=1500),timeout=30).json()
    if not r: break
    kl+=r;st=r[-1][0]+1
    if len(r)<1500: break
D=[dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date() for k in kl];C=np.array([float(k[4]) for k in kl])
reg={};cur=0
for i in range(199,len(C)):
    ma=C[i-199:i+1].mean();cur=1 if C[i]>ma*1.01 else (0 if C[i]<ma*0.99 else cur);reg[D[i]]=cur   # i일 종가 판단 → i+1일 적용
def regime(d): return reg.get(d-dt.timedelta(1))
rng=np.random.default_rng(20261002)
def rep(name,ev):
    e=[(dt.date.fromisoformat(a),b,c,regime(dt.date.fromisoformat(a))) for a,b,c in ev]
    e=[x for x in e if x[3] is not None]
    print(f'== {name} 전체 {len(e)}건 (국면 4칸)')
    for rg in (1,0):
        for sd in ('L','S'):
            v=[x[2] for x in e if x[3]==rg and x[1]==sd];print(f'   국면 {"오름" if rg else "내림"} × {sd}: n={len(v)} 평균 {np.mean(v)*100 if v else float("nan"):+.3f}%')
    sel=[x for x in e if (x[3]==1 and x[1]=='L') or (x[3]==0 and x[1]=='S')]
    v=np.array([x[2] for x in sel]);dd=np.array([x[0].toordinal() for x in sel]);ks=np.unique(dd);g={k:v[dd==k] for k in ks}
    ms=[np.concatenate([g[k] for k in rng.choice(ks,len(ks))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    print(f'   채택(오름=롱·내림=숏): n={len(v)} 평균 {v.mean()*100:+.3f}% 승률 {(v>0).mean()*100:.0f}% CI [{lo*100:+.3f},{hi*100:+.3f}]  0.24%비용 평균 {(v.mean()-0.0012)*100:+.3f}%')
    return len(v)>=100 and v.mean()>0 and lo>0
a=rep('#28 기간 2025-01~2026-10',json.load(open(S+'ev_cur.json')))
b=rep('#32 기간 2023-02~2025-06',json.load(open(S+'ev_oos.json')))
print('판정:','성립' if a and b else '기각')
