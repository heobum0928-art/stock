"""H4': the live bot only ever sees the LAST PRICE at ~5-minute polls; the backtest sees
every bar's HIGH and LOW.  Re-run with a close-only ("poll") observation model."""
import os, numpy as np, pandas as pd
from scipy import stats
import engine as E, window as W
D=os.path.dirname(os.path.abspath(__file__))

def variants(sym, i_ms, mode_list=("bar","poll","poll_srvstop")):
    p=os.path.join(D,"pqx",sym+".npz")
    if not os.path.exists(p): return None
    z=np.load(p); t=z["t"];o=z["o"];h=z["h"];l=z["l"];c=z["c"]
    i=int(np.searchsorted(t,i_ms,side="right")-1)
    if i<0 or i>=len(t)-13: return None
    P0=float(c[i]); j=min(i+1+576,len(c)); sl=slice(i+1,j); bt=t[sl]
    cf=W.cumfund_for(sym,int(t[i]),bt)
    if cf is None: cf=np.zeros(len(bt))
    hh,ll,oo,cc=h[sl],l[sl],o[sl],c[sl]
    out={}
    # true bar-high stop bar (server-side STOP_MARKET would fire here)
    stopline=P0*1.40
    sb=np.nonzero(hh>=stopline)[0]
    srv_bar=int(sb[0]) if len(sb) else None
    for mode in mode_list:
        if mode=="bar":
            f,tr,ex,mae,mfe=E.scan(hh,ll,oo,cc,P0,opt=True)
        else:
            f,tr,ex,mae,mfe=E.scan(cc,cc,cc,cc,P0,opt=True)
        se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,j-i-1); se.cumfund=cf
        r=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
        if mode=="poll_srvstop" and srv_bar is not None and srv_bar<=r["exit_bar"]:
            # server stop fires first: -40% notional * lev, plus fees/slippage
            fill=stopline
            tot=-E.LEV*E.FEE_SIDE - E.LEV*(fill/P0-1) - E.LEV*E.FEE_SIDE - E.LEV*E.STOP_EXTRA
            tot+= E.LEV*float(se.cumfund[srv_bar])
            r={"ret":max(tot,-1.0),"kind":"stop","exit_bar":srv_bar}
        out[mode]=r["ret"]*100; out[mode+"_kind"]=r["kind"]
    out["mae_bar"]=(hh.max()/P0-1)*100; out["mae_close"]=(cc.max()/P0-1)*100
    out["mfe_bar"]=(1-ll.min()/P0)*100;  out["mfe_close"]=(1-cc.min()/P0)*100
    out["srv_would_fire"]= srv_bar is not None
    return out

if __name__=="__main__":
    from live import C
    rows=[]
    for _,r in C.iterrows():
        v=variants(r.symbol,int(r.et.tz_convert("UTC").value//10**6))
        if v is None: continue
        v.update(symbol=r.symbol,entry=r.et,live_m=r.m,out=r["out"],live_mae=r.mae_pct,live_kind=r["cat"])
        rows.append(v)
    M=pd.DataFrame(rows); g=M[~M.out]
    pd.set_option("display.width",250)
    print("=== MATCHED 47 live entries, three observation models (margin-basis %) ===")
    print("live actual              %+.3f"%g.live_m.mean())
    print("bar-extreme model (BT)   %+.3f   (paired diff live-bt %+.2f%%p, p=%.3f)"%(
        g.bar.mean(), (g.live_m-g.bar).mean(), stats.ttest_rel(g.live_m,g.bar)[1]))
    print("5m-poll model            %+.3f   (paired diff live-poll %+.2f%%p, p=%.3f)"%(
        g.poll.mean(), (g.live_m-g.poll).mean(), stats.ttest_rel(g.live_m,g.poll)[1]))
    print("5m-poll + server stop    %+.3f   (paired diff %+.2f%%p, p=%.3f)"%(
        g.poll_srvstop.mean(), (g.live_m-g.poll_srvstop).mean(), stats.ttest_rel(g.live_m,g.poll_srvstop)[1]))
    print("\nMAE observed:  live-recorded %.2f | 5m-close %.2f | true bar-high %.2f"%(
        g.live_mae.mean(), g.mae_close.mean(), g.mae_bar.mean()))
    print("trades where true bar-high crossed +40%% (server stop SHOULD fire): %d/%d"%(g.srv_would_fire.sum(),len(g)))
    print("  ...of which live did NOT record a stop: %d"%((g.srv_would_fire)&(~g.live_kind.isin(["stop","server_stop"]))).sum())
    print(g[g.srv_would_fire&~g.live_kind.isin(["stop","server_stop"])][["symbol","entry","live_m","live_kind","live_mae","mae_close","mae_bar","bar","poll"]].to_string())
    print("\nexit kinds:", {k:int((g[k+"_kind"] if False else g[k+"_kind"]).value_counts().to_dict().get('x',0)) for k in []})
    for k in ("bar","poll","poll_srvstop"):
        print("  %-14s %s"%(k, g[k+"_kind"].value_counts().to_dict()))
    print("  live          %s"%g.live_kind.value_counts().to_dict())
    M.to_pickle(os.path.join(D,"poll_matched.pkl"))
