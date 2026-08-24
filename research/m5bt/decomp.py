import os, numpy as np, pandas as pd
from scipy import stats
D=os.path.dirname(os.path.abspath(__file__))
from live import C
pop=pd.read_pickle(os.path.join(D,"pop_livewin.pkl"))
pri=pd.read_pickle(os.path.join(D,"pop_prior.pkl"))
pm =pd.read_pickle(os.path.join(D,"poll_matched.pkl"))
g=pm[~pm.out]
rng=np.random.default_rng(20260822)
LIVE=g.live_m.mean()
print("="*70)
A=pri.bar.mean(); B=pop.bar.mean(); Cm=g.bar.mean(); Dm=g.poll.mean(); Em=LIVE
print("A backtest prior-year, bar model, n=%d      %+7.3f"%(len(pri),A))
print("B same rule, LIVE WINDOW, all signals        %+7.3f   (n=%d)   period effect %+.2f%%p"%(B,len(pop),B-A))
print("C same window, only the 47 taken entries     %+7.3f              entry selection %+.2f%%p"%(Cm,Cm-B))
print("D same 47, 5m-poll observation model         %+7.3f              observation model %+.2f%%p"%(Dm,Dm-Cm))
print("E live actual                                %+7.3f              residual %+.2f%%p"%(Em,Em-Dm))
print("   TOTAL GAP %+.2f%%p"%(Em-A))
print()
# split D: population-level poll effect vs this-sample poll effect
pe=pop.poll.mean()-pop.bar.mean()
print("  [D split] poll-model effect on the WHOLE live-window population: %+.2f%%p"%pe)
print("            extra poll benefit specific to the 47:                 %+.2f%%p (sample-specific)"%((Dm-Cm)-pe))
print()
# ---- is the 47's selection advantage vs the 199 significant?
x=pop.bar.values
s=rng.choice(x,size=(20000,len(g)),replace=True).mean(1)
print("  [C test] bootstrap %d of the %d live-window signals: P(mean>=%.2f)=%.2f%%"%(len(g),len(pop),Cm,(s>=Cm).mean()*100))
xp=pop.psrv.values
s2=rng.choice(xp,size=(20000,len(g)),replace=True).mean(1)
print("           same but poll+serverstop model:            P(mean>=%.2f)=%.2f%%"%(LIVE,(s2>=LIVE).mean()*100))
# combined: P(live result | frozen rule + live window + poll model)
print("           P(47-draw from live-window psrv >= live actual %.2f) = %.2f%%"%(LIVE,(s2>=LIVE).mean()*100))
# ---- H2 symbol set within the window
ls=set(C.symbol.unique())
sub=pop[pop.sym.isin(ls)]; oth=pop[~pop.sym.isin(ls)]
print()
print("  [H2] live-window signals on live-traded symbols: n=%d mean %+.2f | other symbols n=%d mean %+.2f (Welch p=%.3f)"%(
    len(sub),sub.bar.mean(),len(oth),oth.bar.mean(),stats.ttest_ind(sub.bar,oth.bar,equal_var=False)[1]))
# ---- H5 missed signals: population minus taken
print()
print("  [H5] available signals in live window %d, bot entered %d (%.0f%%)"%(len(pop),len(C),100*len(C)/len(pop)))
tk=set(zip(C.symbol, (C.et.dt.tz_convert('UTC').astype('int64')//10**6//(3600*1000))))
pop['hr']=pop.t0//(3600*1000)
pop['taken']=[ (r.sym,r.hr) in tk or (r.sym,r.hr-1) in tk or (r.sym,r.hr+1) in tk for r in pop.itertuples()]
print("       matched-as-taken %d ; NOT taken %d mean %+.2f (bar) / %+.2f (psrv)"%(
    pop.taken.sum(), (~pop.taken).sum(), pop[~pop.taken].bar.mean(), pop[~pop.taken].psrv.mean()))
print("       taken subset (bar model) %+.2f"%pop[pop.taken].bar.mean())
# ---- H6 segments
print()
print("  [H6] live segments (bug-adjusted):")
segs=[("~08-06 (pre regime filter / pre 3M vol / pre upper-cut / pre trail)","2026-01-01","2026-08-07"),
      ("08-07~08-09 (regime filter + 3M vol + upper cut, no trailing)","2026-08-07","2026-08-10"),
      ("08-10~ (trailing stop live)","2026-08-10","2026-09-01")]
CC=C[~C.out].copy(); CC["d"]=CC.et.dt.tz_localize(None)
for nm,a,b in segs:
    m=(CC.d>=pd.Timestamp(a))&(CC.d<pd.Timestamp(b))
    if m.sum(): print("     %-62s n=%2d mean %+7.2f median %+6.2f"%(nm,m.sum(),CC[m].m.mean(),CC[m].m.median()))
print("     first 21 trades: mean %+.2f | last 26: mean %+.2f"%(CC.m.iloc[:21].mean(),CC.m.iloc[21:].mean()))
# margin size segments
print("     by margin size:"); print(CC.groupby("margin_usdt").m.agg(['size','mean']).to_string())
