import numpy as np, pandas as pd
df=pd.read_pickle('bt.pkl'); df['m']=df.ret_opt*100; df['mp']=df.ret_pes*100
df['day']=(df.t0//86400000).astype(int)
LIVE=9.606; N=47
rng=np.random.default_rng(20260822)
print("live bug-adj mean (margin basis) = %.3f%%, n=%d"%(LIVE,N))
for col,lab in (('m','optimistic'),('mp','pessimistic')):
    x=df[col].values
    # (a) iid resample
    s=rng.choice(x,size=(20000,N),replace=True).mean(1)
    print("\n[%s] BT mean %.3f sd %.2f"%(lab,x.mean(),x.std(ddof=1)))
    print("  (a) iid 47-draw: P(mean>=%.2f) = %.4f%%   (%d/20000)"%(LIVE,(s>=LIVE).mean()*100,(s>=LIVE).sum()))
    print("      sim mean %.2f sd %.2f  p97.5=%.2f p99.9=%.2f max=%.2f"%(s.mean(),s.std(),np.percentile(s,97.5),np.percentile(s,99.9),s.max()))
    # (b) contiguous 31-day window resample (captures regime/serial correlation)
    d0,d1=df.day.min(),df.day.max()
    means=[];ns=[]
    for start in range(d0,d1-30):
        sel=df[(df.day>=start)&(df.day<start+31)]
        if len(sel)<10: continue
        means.append(sel[col].mean()); ns.append(len(sel))
    means=np.array(means)
    print("  (b) every contiguous 31-day window (n=%d windows, median %d signals/window):"%(len(means),int(np.median(ns))))
    print("      window means: min %.2f  p25 %.2f  median %.2f  p75 %.2f  max %.2f"%(
        means.min(),np.percentile(means,25),np.median(means),np.percentile(means,75),means.max()))
    print("      P(31-day window mean >= %.2f) = %.2f%%  (%d/%d)"%(LIVE,(means>=LIVE).mean()*100,(means>=LIVE).sum(),len(means)))
    # (c) day-block bootstrap: draw days with replacement until >=47 signals
    ud=df.day.unique(); byday={d:df[df.day==d][col].values for d in ud}
    out=np.empty(10000)
    for b in range(10000):
        acc=[]
        while sum(len(a) for a in acc)<N:
            acc.append(byday[ud[rng.integers(0,len(ud))]])
        v=np.concatenate(acc)[:N]
        out[b]=v.mean()
    print("  (c) day-block bootstrap (47 signals): P(mean>=%.2f) = %.2f%%  sd=%.2f"%(LIVE,(out>=LIVE).mean()*100,out.std()))
