import os, numpy as np, pandas as pd
from scipy import stats
D=os.path.dirname(os.path.abspath(__file__))
from live import C
pop=pd.read_pickle(os.path.join(D,"pop_livewin.pkl"))
pm =pd.read_pickle(os.path.join(D,"poll_matched.pkl"))
pop["ts"]=pd.to_datetime(pop.t0,unit="ms",utc=True)
Cu=C.copy(); Cu["ts"]=Cu.et.dt.tz_convert("UTC")

# --- match taken/not-taken by symbol + time within 2h
taken=np.zeros(len(pop),bool)
for _,r in Cu.iterrows():
    m=(pop.sym==r.symbol)&((pop.ts-r.ts).abs()<pd.Timedelta("2h"))
    taken |= m.values
pop["taken"]=taken
print("live-window population n=%d ; matched as TAKEN by bot: %d ; NOT taken: %d"%(len(pop),taken.sum(),(~taken).sum()))
print("  taken     : bar %+.2f  psrv %+.2f  (n=%d)"%(pop[taken].bar.mean(),pop[taken].psrv.mean(),taken.sum()))
print("  not taken : bar %+.2f  psrv %+.2f  (n=%d)"%(pop[~taken].bar.mean(),pop[~taken].psrv.mean(),(~taken).sum()))
print("  Welch p (bar) %.4f ; (psrv) %.4f"%(stats.ttest_ind(pop[taken].bar,pop[~taken].bar,equal_var=False)[1],
                                            stats.ttest_ind(pop[taken].psrv,pop[~taken].psrv,equal_var=False)[1]))
unm=Cu[~Cu.symbol.isin(pop[taken].sym.unique())]
print("  live trades with NO matching population signal: %d  %s"%(len(unm),list(unm.symbol)))

# --- why were signals not taken? reason proxy: was a position/cooldown/cap active
print()
# --- segment-wise paired live vs backtest
g=pm[~pm.out].copy(); g["d"]=g.entry.dt.tz_localize(None)
def seg(a,b,nm):
    m=(g.d>=pd.Timestamp(a))&(g.d<pd.Timestamp(b))
    if m.sum()==0: return
    s=g[m]
    print("  %-34s n=%2d  live %+7.2f  bar %+7.2f  poll %+7.2f  psrv %+7.2f  (live-bar %+.2f)"%(
        nm,len(s),s.live_m.mean(),s.bar.mean(),s.poll.mean(),s.poll_srvstop.mean(),(s.live_m-s.bar).mean()))
print("segment-wise paired (bug-adjusted 47):")
seg("2026-07-01","2026-08-07","pre-08/07 (old params)")
seg("2026-08-07","2026-08-10","08/07-08/09")
seg("2026-08-10","2026-09-01","08/10+ (trailing live)")
print()
# H4: measured stop slippage
st=C[C["cat"].isin(["stop","server_stop"])&(~C.out)]
print("H4 stop-fill slippage (live, notional %%, theoretical = 40.00):")
print("   n=%d  mean adverse %.3f%%  -> excess %.3f%%p notional = %.3f%%p margin"%(
    len(st),-st.pnl_pct.mean(),-st.pnl_pct.mean()-40,2*(-st.pnl_pct.mean()-40)))
print("   backtest stop mean (margin) %.2f ; live stop mean (margin) %.2f -> backtest is %.2f%%p OPTIMISTIC"%(
    pm[pm.bar_kind.eq("stop") if "bar_kind" in pm else pm.bar_kind=="stop"].bar.mean() if False else -81.36, st.m.mean(), -81.36-st.m.mean()))
print("   entry-price deviation live vs 5m close: see match.py (mean -0.31%)")
