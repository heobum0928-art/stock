import pandas as pd, numpy as np, re, json
FLD=["entry_time","exit_time","symbol","pump_2h","vol_mult","entry_price","exit_price",
     "margin_usdt","pnl_pct","pnl_usdt","live","reason","btc_entry","btc_exit",
     "mfe_pct","mae_pct","listing_age_days","qvol_24h"]
C=pd.read_csv(r"C:\coinbase\data\margin_short_trades.csv",skiprows=1,names=FLD)
L=pd.read_csv(r"C:\coinbase\data\margin_short_ledger.csv")
C["et"]=pd.to_datetime(C.entry_time,format='ISO8601'); C["xt"]=pd.to_datetime(C.exit_time,format='ISO8601')
C["m"]=C.pnl_pct*2.0                       # margin basis %
C["out"]=C.pnl_pct < -50                   # pre-registered outlier rule
def cat(r):
    if "스탑" in r and "서버측" in r: return "server_stop"
    if "스탑" in r: return "stop"
    if "트레일링" in r: return "trail"
    if "만기" in r: return "expiry"
    return "other"
C["cat"]=C.reason.map(cat)
C["manual"]=C.reason.str.contains("수동")
C["downtime"]=C.reason.str.contains("다운")
C["hold_h"]=(C.xt-C.et).dt.total_seconds()/3600

if __name__=="__main__":
    pd.set_option("display.width",250)
    print("n=",len(C), " period", C.et.min(), "->", C.xt.max())
    g=C[~C.out]
    print("\n== ALL n=%d ==  mean margin%% %.3f"%(len(C),C.m.mean()))
    print("== bug-adjusted n=%d ==  mean %.3f sd %.3f se %.3f median %.2f win%% %.1f"%(
        len(g),g.m.mean(),g.m.std(ddof=1),g.m.std(ddof=1)/len(g)**.5,g.m.median(),(g.m>0).mean()*100))
    print("\nby exit reason (bug-adj):")
    print(g.groupby("cat").agg(n=("m","size"),mean=("m","mean"),med=("m","median"),win=("m",lambda x:(x>0).mean()*100)))
    print("\nmanual-intervention rows:"); print(C[C.manual][["entry_time","symbol","pnl_pct","reason"]].to_string())
    print("\ndowntime rows:"); print(C[C.downtime][["entry_time","symbol","pnl_pct","hold_h","reason"]].to_string())
    print("\npump>=40 (current rule would EXCLUDE these):")
    print(C[C.pump_2h>=40][["entry_time","symbol","pump_2h","pnl_pct","reason"]].to_string())
    print("  their mean margin%%: %.2f (n=%d)"%(C[C.pump_2h>=40].m.mean(),(C.pump_2h>=40).sum()))
    print("\nhold_h > 48.5h (overrun):")
    print(C[C.hold_h>48.5][["entry_time","symbol","hold_h","pnl_pct","reason"]].to_string())
    print("\nn symbols",C.symbol.nunique()); print(sorted(C.symbol.unique()))
    # duplicate-symbol within 12h (ledger contamination analogue)
    C2=C.sort_values(["symbol","et"])
    bad=[]
    for s,grp in C2.groupby("symbol"):
        x=grp.sort_values("xt")
        for i in range(len(x)-1):
            d=(x.xt.iloc[i+1]-x.xt.iloc[i]).total_seconds()/3600
            if d<12: bad.append((s,str(x.xt.iloc[i]),str(x.xt.iloc[i+1]),round(d,2)))
    print("\nsame-symbol exits within 12h (ledger-matching risk):",len(bad))
    for b in bad: print("  ",b)
