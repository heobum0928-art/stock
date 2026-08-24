"""Population-level: same frozen rule, three observation models, two windows."""
import os, glob, sys
import numpy as np, pandas as pd
import engine as E, window as W
D=os.path.dirname(os.path.abspath(__file__))
PQ=os.path.join(D,"pqx")
LB=84; VW=288; MINQV=3_000_000; CD=12*3600*1000; NEW=30*24*3600*1000; HB=576

def run(WIN_S,WIN_E,tag):
    syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,"*.npz")))
    rows=[]
    for s in syms:
        z=np.load(os.path.join(PQ,s+".npz"))
        t,o,h,l,c,qv=z["t"],z["o"],z["h"],z["l"],z["c"],z["qv"]
        n=len(t)
        if n<LB+VW+100: continue
        M=300000
        ok_lb=np.zeros(n,bool); ok_lb[LB:]=(t[LB:]-t[:-LB])==LB*M
        ok_vw=np.zeros(n,bool); ok_vw[VW-1:]=(t[VW-1:]-t[:n-VW+1])==(VW-1)*M
        ret=np.full(n,np.nan); ret[LB:]=(c[LB:]/c[:-LB]-1)*100
        cs=np.concatenate(([0.0],np.cumsum(qv)))
        v24=np.full(n,np.nan); v24[VW-1:]=cs[VW:]-cs[:n-VW+1]
        cand=(t>=WIN_S)&(t<WIN_E)&ok_lb&ok_vw&((t-t[0])>=NEW)&(ret>=30)&(ret<40)&(v24>=MINQV)
        last=-10**18
        for i in np.nonzero(cand)[0]:
            if t[i]-last<CD: continue
            last=t[i]
            P0=float(c[i]); j=min(i+1+HB,len(c))
            if j-(i+1)<12: continue
            sl=slice(i+1,j); bt=t[sl]
            cf=W.cumfund_for(s,int(t[i]),bt)
            if cf is None: cf=np.zeros(len(bt))
            hh,ll,oo,cc=h[sl],l[sl],o[sl],c[sl]
            sb=np.nonzero(hh>=P0*1.40)[0]; srv=int(sb[0]) if len(sb) else None
            r={}
            for mode in ("bar","barpes","poll"):
                if mode=="bar":   f,tr,ex,mae,mfe=E.scan(hh,ll,oo,cc,P0,opt=True)
                elif mode=="barpes": f,tr,ex,mae,mfe=E.scan(hh,ll,oo,cc,P0,opt=False)
                else:             f,tr,ex,mae,mfe=E.scan(cc,cc,cc,cc,P0,opt=True)
                se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,j-i-1); se.cumfund=cf
                x=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
                r[mode]=x["ret"]*100; r[mode+"k"]=x["kind"]
                if mode=="poll": pb=x["exit_bar"]
            # poll + server-side stop
            if srv is not None and srv<=pb:
                fill=P0*1.40
                tot=-E.LEV*E.FEE_SIDE-E.LEV*(fill/P0-1)-E.LEV*E.FEE_SIDE-E.LEV*E.STOP_EXTRA+E.LEV*float(cf[srv])
                r["psrv"]=max(tot,-1.0)*100; r["psrvk"]="stop"
            else:
                r["psrv"]=r["poll"]; r["psrvk"]=r["pollk"]
            r.update(sym=s,t0=int(t[i]),ret7h=float(ret[i]))
            rows.append(r)
    df=pd.DataFrame(rows); df.to_pickle(os.path.join(D,"pop_%s.pkl"%tag))
    print("\n### %s  n=%d signals, %d symbols"%(tag,len(df),df.sym.nunique()))
    for m in ("bar","barpes","poll","psrv"):
        print("  %-8s mean %+7.3f  median %+6.2f  win%% %5.1f  stop%% %5.1f"%(
            m, df[m].mean(), df[m].median(), (df[m]>0).mean()*100,
            (df[m+"k"]=="stop").mean()*100))
    return df

if __name__=="__main__":
    ms=lambda s:int(pd.Timestamp(s,tz="UTC").value//10**6)
    run(ms("2026-07-22 08:00"),ms("2026-08-19 12:00"),"livewin")
    run(ms("2025-08-01 00:00"),ms("2026-07-22 08:00"),"prior")
