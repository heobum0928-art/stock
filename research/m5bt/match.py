"""Paired head-to-head: each live trade vs the backtest simulation of THE SAME signal."""
import os, numpy as np, pandas as pd
from scipy import stats
import engine as E, window as W
D=os.path.dirname(os.path.abspath(__file__))
from live import C

pop=pd.read_pickle(os.path.join(D,"win_live.pkl"))
pop["ts"]=pd.to_datetime(pop.t0,unit="ms",utc=True)

# --- simulate each live trade from its OWN entry bar (not the population signal bar) ---
def sim_at(sym, entry_utc_ms):
    p=os.path.join(D,"pqx",sym+".npz")
    if not os.path.exists(p): return None
    z=np.load(p); t=z["t"];o=z["o"];h=z["h"];l=z["l"];c=z["c"]
    i=int(np.searchsorted(t,entry_utc_ms,side="right")-1)
    if i<0 or i>=len(t)-13: return None
    P0=float(c[i]); j=min(i+1+576,len(c)); sl=slice(i+1,j); bt=t[sl]
    cf=W.cumfund_for(sym,int(t[i]),bt)
    if cf is None: cf=np.zeros(len(bt))
    out={}
    for tag,opt in (("opt",True),("pes",False)):
        f,tr,ex,mae,mfe=E.scan(h[sl],l[sl],o[sl],c[sl],P0,opt=opt)
        se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,j-i-1); se.cumfund=cf
        r=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
        out[tag]=r["ret"]*100; out[tag+"_kind"]=r["kind"]
        if tag=="opt": out["mae"]=mae; out["mfe"]=mfe; out["P0"]=P0
    return out

rows=[]
for _,r in C.iterrows():
    ems=int(r.et.tz_convert("UTC").value//10**6)
    s=sim_at(r.symbol,ems)
    d=dict(symbol=r.symbol, entry=r.et, live_m=r.m, live_kind=r["cat"], out=r.out,
           pump=r.pump_2h, live_mfe=r.mfe_pct, live_mae=r.mae_pct, live_px=r.entry_price)
    if s: d.update(bt_m=s["opt"], bt_mp=s["pes"], bt_kind=s["opt_kind"], bt_kindp=s["pes_kind"],
                   bt_mae=s["mae"], bt_mfe=s["mfe"], bt_px=s["P0"])
    rows.append(d)
M=pd.DataFrame(rows)
M["pxdiff"]=(M.live_px/M.bt_px-1)*100
M.to_pickle(os.path.join(D,"matched.pkl"))
pd.set_option("display.width",250)
print("matched %d/%d"%(M.bt_m.notna().sum(),len(M)))
g=M[(~M.out)&M.bt_m.notna()]
print("\n=== PAIRED (bug-adjusted n=%d) ==="%len(g))
print("live mean %.3f   bt(opt) %.3f   bt(pes) %.3f"%(g.live_m.mean(),g.bt_m.mean(),g.bt_mp.mean()))
d=g.live_m-g.bt_m
print("paired diff (live - bt_opt): %+.3f%%p  sd %.2f  t=%.2f p=%.4g"%(d.mean(),d.std(ddof=1),*stats.ttest_rel(g.live_m,g.bt_m)))
d2=g.live_m-g.bt_mp
print("paired diff (live - bt_pes): %+.3f%%p  t=%.2f p=%.4g"%(d2.mean(),*stats.ttest_rel(g.live_m,g.bt_mp)))
print("\nentry-price deviation (live vs 5m bar close): mean %+.3f%% median %+.3f%% |max| %.2f%%"%(
    g.pxdiff.mean(),g.pxdiff.median(),g.pxdiff.abs().max()))
print("\nexit-kind cross-tab (live rows x bt rows):")
print(pd.crosstab(g.live_kind,g.bt_kind))
print("\nper-trade table:")
print(g[["symbol","entry","pump","live_m","bt_m","bt_mp","live_kind","bt_kind","live_mae","bt_mae","pxdiff"]].to_string())
print("\nALL 49 incl outliers: live %.3f  bt %.3f"%(M.live_m.mean(),M.bt_m.mean()))
