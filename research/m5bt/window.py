"""Run the frozen rule over an arbitrary window using pqx (extended to 2026-08-21)."""
import os, glob, sys, json
import numpy as np, pandas as pd
import engine as E
D=os.path.dirname(os.path.abspath(__file__))
PQ=os.path.join(D,"pqx"); FD=os.path.join(D,"fund")
LOOKBACK=84; VOLWIN=288; MIN_QV=3_000_000
PUMP_LO,PUMP_HI=30.0,40.0
COOLDOWN_MS=12*3600*1000; NEWLIST_MS=30*24*3600*1000
HOLD_BARS=576

def ms(s): return int(pd.Timestamp(s,tz="UTC").value//10**6)

def cumfund_for(sym,t0,bt):
    p=os.path.join(FD,sym+".npz")
    if not os.path.exists(p): return None
    z=np.load(p); ft=z[z.files[0]]; fr=z[z.files[1]]
    cs=np.concatenate(([0.0],np.cumsum(fr)))
    lo=np.searchsorted(ft,t0,side="right"); hi=np.searchsorted(ft,bt,side="right")
    return cs[hi]-cs[lo]

def run(WIN_S, WIN_E, pump_hi=PUMP_HI, pump_lo=PUMP_LO, min_qv=MIN_QV, syms=None, need_fund=True):
    if syms is None:
        syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,"*.npz")))
    rows=[]; nofund=0
    for s in syms:
        p=os.path.join(PQ,s+".npz")
        if not os.path.exists(p): continue
        z=np.load(p); t=z["t"];o=z["o"];h=z["h"];l=z["l"];c=z["c"];qv=z["qv"]
        n=len(t)
        if n<LOOKBACK+VOLWIN+100: continue
        M=300000
        ok_lb=np.zeros(n,bool); ok_lb[LOOKBACK:]=(t[LOOKBACK:]-t[:-LOOKBACK])==LOOKBACK*M
        ok_vw=np.zeros(n,bool); ok_vw[VOLWIN-1:]=(t[VOLWIN-1:]-t[:n-VOLWIN+1])==(VOLWIN-1)*M
        ret=np.full(n,np.nan); ret[LOOKBACK:]=(c[LOOKBACK:]/c[:-LOOKBACK]-1)*100
        cs=np.concatenate(([0.0],np.cumsum(qv)))
        v24=np.full(n,np.nan); v24[VOLWIN-1:]=cs[VOLWIN:]-cs[:n-VOLWIN+1]
        age=(t-t[0])>=NEWLIST_MS
        inwin=(t>=WIN_S)&(t<WIN_E)
        cand=inwin&ok_lb&ok_vw&age&(ret>=pump_lo)&(ret<pump_hi)&(v24>=min_qv)
        idx=np.nonzero(cand)[0]
        last=-10**18
        for i in idx:
            if t[i]-last<COOLDOWN_MS: continue
            last=t[i]
            P0=float(c[i]); j=min(i+1+HOLD_BARS,len(c))
            if j-(i+1)<12: continue
            sl=slice(i+1,j); bt=t[sl]
            cf=cumfund_for(s,int(t[i]),bt)
            if cf is None:
                nofund+=1; cf=np.zeros(len(bt))
            r={}
            for tag,opt in (("opt",True),("pes",False)):
                f,tr,ex,mae,mfe=E.scan(h[sl],l[sl],o[sl],c[sl],P0,opt=opt)
                se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,j-i-1); se.cumfund=cf
                rr=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
                r[tag]=rr
                if tag=="opt": r["mae"]=mae; r["mfe"]=mfe
            rows.append(dict(sym=s,t0=int(t[i]),P0=P0,ret7h=float(ret[i]),qv24=float(v24[i]),
                             m=r["opt"]["ret"]*100, mp=r["pes"]["ret"]*100,
                             kind=r["opt"]["kind"], kindp=r["pes"]["kind"],
                             xt=r["opt"]["exit_ts"], mae=r["mae"], mfe=r["mfe"],
                             truncated=(j-(i+1))<HOLD_BARS))
    df=pd.DataFrame(rows)
    df.attrs["nofund"]=nofund
    return df

if __name__=="__main__":
    S,Eend=ms("2026-07-22 08:00"), ms("2026-08-19 12:00")
    df=run(S,Eend)
    df.to_pickle(os.path.join(D,"win_live.pkl"))
    print("live-window signals n=%d (symbols %d), no-funding %d, truncated %d"%(
        len(df),df.sym.nunique(),df.attrs["nofund"],df.truncated.sum()))
    print("mean opt %.3f  pes %.3f  median %.2f  win%% %.1f"%(df.m.mean(),df.mp.mean(),df.m.median(),(df.m>0).mean()*100))
    print(df.groupby("kind").agg(n=("m","size"),mean=("m","mean")))
