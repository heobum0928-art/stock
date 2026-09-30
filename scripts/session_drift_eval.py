"""prereg #17 PREREG_SESSION_DRIFT.md"""
import numpy as np
W={'아시아':(0,8),'미국':(13,21)}
def daily(path):
    z=np.load(path);t=z['t']//1000;o=z['o'];c=z['c'];day=t//86400;hr=(t%86400)//3600
    out={}
    for name,(a,b) in W.items():
        for d in np.unique(day):
            m=(day==d)&(hr>=a)&(hr<b)
            if m.sum()>=(b-a)*12*0.9: out.setdefault(name,{})[int(d)]=c[m][-1]/o[m][0]-1
    return out
rng=np.random.default_rng(20260930);ok=[]
print('종목 창 구간 n 일평균(비용후)')
for s in ('BTCUSDT','ETHUSDT','SOLUSDT'):
    A=daily(f'research/m5bt/pq_bull/{s}.npz');B=daily(f'research/m5bt/pq/{s}.npz')
    for w in W:
        xa=np.array(list(A[w].values()))-0.001;xb=np.array(list(B[w].values()))-0.001;x=np.r_[xa,xb]
        ms=np.array([x[rng.integers(0,len(x),len(x))].mean() for _ in range(4000)]);lo=np.percentile(ms,100*0.05/6/2)
        print(f'{s} {w}  전기 n={len(xa)} {xa.mean()*100:+.3f}%  후기 n={len(xb)} {xb.mean()*100:+.3f}%  전체 {x.mean()*100:+.3f}% CI하한(99.17%) {lo*100:+.3f}%')
        if xa.mean()>0 and xb.mean()>0 and lo>0: ok.append((s,w))
    d=np.array([A['미국'][k]-A['아시아'][k] for k in A['미국'] if k in A['아시아']])
    print(f'  {s} 미국−아시아(전기) {d.mean()*100:+.3f}%/일')
print('판정:', f'성립 {ok}' if ok else '기각')
