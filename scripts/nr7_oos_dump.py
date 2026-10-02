"""prereg #32 PREREG_NR7_OOS.md"""
import os,glob,numpy as np,datetime as dt
D='research/m5bt/pq_bull'
d0=dt.date(2023,1,1);d1=dt.date(2025,6,30);nd=(d1-d0).days+1
sy=[];HR={};DAY={}
for f in sorted(glob.glob(D+'/*.npz')):
    s=os.path.basename(f)[:-4]
    if s in ('BTCUSDT','ETHUSDT','USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT'): continue
    z=np.load(f);t=z['t']//1000;h=z['h'];l=z['l'];c=z['c'];o=z['o'];qv=z['qv']
    hr=t//3600;ud,idx=np.unique(hr,return_index=True);ends=np.r_[idx[1:],len(t)]
    H=[(int(u),h[a:b].max(),l[a:b].min(),c[b-1]) for u,a,b in zip(ud,idx,ends)]
    HR[s]=H
    dd=t//86400;dk={}
    for u,a,b in zip(*[np.unique(dd,return_index=True)[0],np.unique(dd,return_index=True)[1],np.r_[np.unique(dd,return_index=True)[1][1:],len(t)]]):
        dk[int(u)]=(h[a:b].max(),l[a:b].min(),c[b-1],qv[a:b].sum())
    DAY[s]=dk
base=int(dt.datetime(2023,1,1,tzinfo=dt.timezone.utc).timestamp())//86400
def run(cost):
    ev=[]
    for di in range(40,nd):
        d=base+di;vols={}
        for s,dk in DAY.items():
            w=[dk.get(d-i) for i in range(1,31)]
            if all(w): vols[s]=sum(x[3] for x in w)
        for s in sorted(vols,key=vols.get,reverse=True)[:20]:
            dk=DAY[s];rg=[(dk[d-i][0]-dk[d-i][1])/dk[d-i][2] for i in range(1,8) if (d-i) in dk]
            if len(rg)<7 or rg[0]!=min(rg): continue
            hi,lo=dk[d-1][0],dk[d-1][1]
            hb=[x for x in HR[s] if x[0]//24==d]
            if len(hb)<20: continue
            side=None
            for (_,h,l,c) in hb:
                up=h>hi;dn=l<lo
                if up and dn: side='skip';break
                if up: side='L';break
                if dn: side='S';break
            if side in (None,'skip'): continue
            entry=hi if side=='L' else lo;stop=lo if side=='L' else hi;started=False;exitp=hb[-1][3]
            for (_,h,l,c) in hb:
                if not started:
                    if (side=='L' and h>hi) or (side=='S' and l<lo): started=True
                    continue
                if side=='L' and l<=stop: exitp=stop;break
                if side=='S' and h>=stop: exitp=stop;break
            r=(exitp/entry-1) if side=='L' else (entry/exitp-1)
            ev.append((d,s,side,r-cost))
    return ev
import json
for cost in (0.0012,):
    ev=run(cost);json.dump([[str(dt.date(1970,1,1)+dt.timedelta(int(e[0]))),e[2],float(e[3])] for e in ev],open('C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/ev_oos.json','w'));x=np.array([e[3] for e in ev]);n=len(x)
    print(f'== 비용 {cost*100:.2f}% 건수 {n}')
    if not n: continue
    dd=np.array([e[0] for e in ev]);ks=np.unique(dd);g={k:x[dd==k] for k in ks};rng=np.random.default_rng(20261002)
    ms=[np.concatenate([g[k] for k in rng.choice(ks,len(ks))]).mean() for _ in range(4000)];lo_,hi_=np.percentile(ms,[2.5,97.5])
    cut=int(dt.datetime(2024,5,1,tzinfo=dt.timezone.utc).timestamp())//86400;a=x[dd<cut];b=x[dd>=cut]
    print(f'평균 {x.mean()*100:+.3f}% 중앙 {np.median(x)*100:+.3f}% 승률 {(x>0).mean()*100:.0f}% CI [{lo_*100:+.3f},{hi_*100:+.3f}] 평균이익 {x[x>0].mean()*100:+.2f}% 평균손실 {x[x<=0].mean()*100:+.2f}% 상위10 이익비중 {np.sort(x)[::-1][:10].clip(0).sum()/x.clip(0).sum()*100:.0f}%')
    print(f'전반 n={len(a)} {a.mean()*100:+.3f}%  후반 n={len(b)} {b.mean()*100:+.3f}%')
    for sd in ('L','S'): m=np.array([e[2]==sd for e in ev]);print(f'  {sd}: n={m.sum()} {x[m].mean()*100:+.3f}%')
    if cost==0.0012: print('판정:','판별 불가' if n<100 else ('성립' if x.mean()>0 and lo_>0 and a.mean()>0 and b.mean()>0 else '기각'))
