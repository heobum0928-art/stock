"""prereg #35 PREREG_EXTREME_FLEET.md (기간 B 이벤트 추출)"""
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
            entry=hi if side=='L' else lo;stop=lo if side=='L' else hi
            started=False;after=[]
            for (_,h,l,c) in hb:
                if not started:
                    if (side=='L' and h>hi) or (side=='S' and l<lo): started=True
                    else: continue
                after.append((h,l,c))
            mx=max(a[0] for a in after);mn=min(a[1] for a in after);cl=hb[-1][3]
            stopped=False;exitp=cl;adv_stop=0.0
            for (h,l,c) in after:
                a=(entry-l)/entry if side=='L' else (h-entry)/entry
                adv_stop=max(adv_stop,a)
                if side=='L' and l<=stop: exitp=stop;break
                if side=='S' and h>=stop: exitp=stop;break
            adv=(entry-mn)/entry if side=='L' else (mx-entry)/entry
            rs=(exitp/entry-1) if side=='L' else (entry/exitp-1);rc=(cl/entry-1) if side=='L' else (entry/cl-1)
            ev.append((str(dt.date(1970,1,1)+dt.timedelta(int(d))),s,side,rs,rc,adv,adv_stop))
    return ev
import json;ev=run(0);json.dump(ev,open('C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/ext_B.json','w'));print('B 이벤트',len(ev))
