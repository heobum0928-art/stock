import os, json, pickle, math
import numpy as np
from scipy import stats
import engine as E, analyze as A

D=os.path.dirname(os.path.abspath(__file__))
P=lambda *a: print(*a, flush=True)
if os.path.exists(os.path.join(D,"events.pkl")):
    dat=pickle.load(open(os.path.join(D,"events.pkl"),"rb"))
else:
    import build; dat=build.main()
real=dat["real"]; rand=dat["rand"]; meta=dat["meta"]
P("== META =="); P(json.dumps(meta,indent=1))
t0=np.array([r["t0"] for r in real]); days=(t0//86400000)
hold=np.array([r["hold"] for r in real])
regime=np.array([r["regime"] for r in real])
P("period: %s .. %s"%(np.datetime64(int(t0.min()),'ms'),np.datetime64(int(t0.max()),'ms')))
P("train/holdout signals: %d / %d"%((~hold).sum(),hold.sum()))
P("regimes:", {k:int((regime==k).sum()) for k in set(regime.tolist())})
P("truncated (delisted mid-trade):", sum(r["truncated"] for r in real))

cfgs=A.build_grid(); keys=list(cfgs)
NTEST=len(keys)-1
P("grid size: %d (staged %d, single-stop baselines 4); comparisons vs current: %d"%(len(keys),len(keys)-4,NTEST))

RES={}
for which in ("opt","pes"):
    for extra in (0.0, 0.001):
        k,R,LIQ,XT,NF=A.evalall(real,cfgs,which=which,extra=extra)
        RES[(which,extra)]=(R,LIQ,XT,NF)
        P("evaluated",which,extra)
for which in ("opt","pes"):
    k,R,LIQ,XT,NF=A.evalall(real,cfgs,which=which,extra=0.0,use_fund=False)
    RES[(which,"nofund")]=(R,LIQ,XT,NF)
    P("evaluated",which,"nofund")


def summ(R,LIQ,NF,mask):
    r=R[:,mask]
    return dict(mean=r.mean(1)*100, med=np.median(r,1)*100, std=r.std(1,ddof=1)*100,
                win=(r>0).mean(1)*100, liq=LIQ[:,mask].mean(1)*100,
                worst=r.min(1)*100, nf=NF[:,mask].mean(1))

def pair(R,i,j,mask,dd):
    d=(R[i,mask]-R[j,mask])
    t,p=stats.ttest_rel(R[i,mask],R[j,mask])
    ci,_=A.day_boot(d,dd)
    return d.mean()*100, ci[0]*100, ci[1]*100, t, p

BASE=keys.index((None,0.0,40.0,40.0))
P("\n== BASELINE INDEX ==", keys[BASE], cfgs[keys[BASE]])
json.dump({"keys":[list(map(lambda x: x if x is not None else -1,k)) for k in keys],
           "names":[cfgs[k] for k in keys]}, open(os.path.join(D,"keys.json"),"w"))

def bh(pv):
    p=np.asarray(pv); n=len(p); o=np.argsort(p); q=np.empty(n)
    prev=1.0
    for rank in range(n-1,-1,-1):
        i=o[rank]; v=min(prev, p[i]*n/(rank+1)); q[i]=v; prev=v
    return q

TRAIN=~hold; HOLD=hold
def table(which, extra, mask, label, top=None, order_by=None):
    R,LIQ,XT,NF=RES[(which,extra)]
    s=summ(R,LIQ,NF,mask)
    dd=days[mask]
    rows=[]
    for i,k in enumerate(keys):
        d=(R[i,mask]-R[BASE,mask])
        if i==BASE: t=p=0.0; t=np.nan; p=1.0
        else:
            t,p=stats.ttest_rel(R[i,mask],R[BASE,mask])
        rows.append((cfgs[k], s["mean"][i], s["med"][i], s["win"][i], s["std"][i],
                     s["liq"][i], s["worst"][i], s["nf"][i], d.mean()*100, t, p, i))
    pv=np.array([r[10] for r in rows]); q=bh(pv); bf=np.minimum(pv*NTEST,1.0)
    rows=[r+(bf[n],q[n]) for n,r in enumerate(rows)]
    key=(lambda r:-r[1]) if order_by is None else order_by
    rows.sort(key=key)
    P("\n=== %s  [%s, extra_fill=%.3f%%, n=%d] ==="%(label,which,extra*100,mask.sum()))
    P("%-18s %7s %7s %6s %7s %6s %8s %5s | %8s %7s %9s %9s %9s"%(
        "rule","mean%","med%","win%","sd%","liq%","worst%","fills","diff%","t","p","p_bonf","q_BH"))
    for r in (rows if top is None else rows[:top]):
        P("%-18s %7.2f %7.2f %6.1f %7.1f %6.2f %8.1f %5.2f | %8.2f %7.2f %9.4f %9.4f %9.4f"%
          (r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9],r[10],r[12],r[13]))
    return rows

P("\n\n########## 1) TRAIN SCAN (75% of symbols) ##########")
rows_o=table("opt",0.0,TRAIN,"TRAIN optimistic",top=20)
rows_p=table("pes",0.0,TRAIN,"TRAIN pessimistic",top=20)

# pre-registered selection: mean of (opt+pes)/2 on TRAIN, proportional fees
Ro=RES[("opt",0.0)][0]; Rp=RES[("pes",0.0)][0]
score=((Ro[:,TRAIN].mean(1)+Rp[:,TRAIN].mean(1))/2)
bestidx=int(np.argmax(score))
staged_only=[i for i,k in enumerate(keys) if k[0] is not None]
best_staged=staged_only[int(np.argmax(score[staged_only]))]
singles=[i for i,k in enumerate(keys) if k[0] is None]
best_single=singles[int(np.argmax(score[singles]))]
P("\nBEST overall (TRAIN, avg of opt/pes): %s  score %.3f%%"%(cfgs[keys[bestidx]],score[bestidx]*100))
P("BEST staged  (TRAIN): %s  score %.3f%%"%(cfgs[keys[best_staged]],score[best_staged]*100))
P("BEST single  (TRAIN): %s  score %.3f%%"%(cfgs[keys[best_single]],score[best_single]*100))

MINIMAX=keys.index((12.0,0.5,20.0,20.0))
P("NOTE MiniMax original (-12%% half, tighten to -25%%, full at -20%%): the -25%% tightening is")
P("     dominated by the -20%% full line, so it reduces to %s"%cfgs[keys[MINIMAX]])

CAND={"current single-40":BASE,"single-20":keys.index((None,0.0,20.0,20.0)),
      "single-25":keys.index((None,0.0,25.0,25.0)),"single-30":keys.index((None,0.0,30.0,30.0)),
      "MiniMax orig":MINIMAX,"TRAIN-best staged":best_staged,"TRAIN-best single":best_single,
      "TRAIN-best overall":bestidx}

def head2head(i,j,mask,which,extra,labi,labj):
    R=RES[(which,extra)][0]
    a=R[i,mask]; b=R[j,mask]; d=a-b
    t,p=stats.ttest_rel(a,b)
    ci,_=A.day_boot(d,days[mask])
    return dict(a=labi,b=labj,mean_a=a.mean()*100,mean_b=b.mean()*100,diff=d.mean()*100,
                lo=ci[0]*100,hi=ci[1]*100,t=t,p=p,n=int(mask.sum()))

P("\n\n########## 2) PAIRED HEAD-TO-HEAD vs CURRENT (single -40) ##########")
for mlab,mask in (("TRAIN",TRAIN),("HOLDOUT",HOLD),("ALL",np.ones(len(real),bool))):
    for which in ("opt","pes"):
        P("\n-- %s / %s --"%(mlab,which))
        P("%-22s %8s %8s %8s %17s %7s %9s"%("rule","mean%","cur%","diff%","95%CI(day-boot)","t","p"))
        for lab,i in CAND.items():
            if i==BASE: continue
            r=head2head(i,BASE,mask,which,0.0,lab,"single-40")
            P("%-22s %8.2f %8.2f %8.2f  [%6.2f, %6.2f] %7.2f %9.5f"%(lab,r["mean_a"],r["mean_b"],r["diff"],r["lo"],r["hi"],r["t"],r["p"]))

P("\n\n########## 3) STAGED vs BEST SIMPLE STOP (the core question) ##########")
for mlab,mask in (("TRAIN",TRAIN),("HOLDOUT",HOLD),("ALL",np.ones(len(real),bool))):
    for which in ("opt","pes"):
        r=head2head(best_staged,best_single,mask,which,0.0,cfgs[keys[best_staged]],cfgs[keys[best_single]])
        P("%-8s %-4s  %-16s %6.2f%%  vs  %-12s %6.2f%%   diff %+6.2f%% [%6.2f,%6.2f] t=%5.2f p=%.4f"%(
            mlab,which,r["a"],r["mean_a"],r["b"],r["mean_b"],r["diff"],r["lo"],r["hi"],r["t"],r["p"]))
        r2=head2head(MINIMAX,best_single,mask,which,0.0,"MiniMax","best single")
        P("%-8s %-4s  %-16s %6.2f%%  vs  %-12s %6.2f%%   diff %+6.2f%% [%6.2f,%6.2f] t=%5.2f p=%.4f"%(
            mlab,which,"MiniMax",r2["mean_a"],r2["b"],r2["mean_b"],r2["diff"],r2["lo"],r2["hi"],r2["t"],r2["p"]))

P("\n\n########## 4) MULTIPLE TESTING ON TRAIN ##########")
for which in ("opt","pes"):
    R=RES[(which,0.0)][0]
    pv=[];tv=[]
    for i,k in enumerate(keys):
        if i==BASE: continue
        t,p=stats.ttest_rel(R[i,TRAIN],R[BASE,TRAIN]); pv.append(p); tv.append(t)
    pv=np.array(pv); tv=np.array(tv)
    pos=(tv>0)
    P("%s: tests=%d, raw p<0.05 = %d (of which better-than-current %d); expected by chance %.1f"%(
        which,NTEST,(pv<0.05).sum(),((pv<0.05)&pos).sum(),0.05*NTEST))
    P("   Bonferroni p<0.05: %d ; BH-FDR q<0.05: %d ; q<0.10: %d"%(
        (pv*NTEST<0.05).sum(),(bh(pv)<0.05).sum(),(bh(pv)<0.10).sum()))

P("\n\n########## 5) WHAT PARTIAL EXIT ACTUALLY CHANGES (ALL signals, opt) ##########")
R,LIQ,XT,NF=RES[("opt",0.0)]
ALLM=np.ones(len(real),bool)
s=summ(R,LIQ,NF,ALLM)
P("%-20s %7s %7s %6s %7s %6s %8s %8s %7s"%("rule","mean%","med%","win%","sd%","liq%","worst%","avgloss%","avgwin%"))
for lab,i in CAND.items():
    r=R[i]; L=r[r<0]; W=r[r>0]
    P("%-20s %7.2f %7.2f %6.1f %7.1f %6.2f %8.1f %8.2f %7.2f"%(
        lab,s["mean"][i],s["med"][i],s["win"][i],s["std"][i],s["liq"][i],s["worst"][i],
        L.mean()*100 if len(L) else 0, W.mean()*100 if len(W) else 0))

P("\n\n########## 6) REGIME SPLIT (opt, ALL) ##########")
for reg in ("bull","bear","chop"):
    m=(regime==reg)
    if m.sum()<30: continue
    P("-- %s (n=%d) --"%(reg,m.sum()))
    for lab,i in CAND.items():
        d=R[i,m]-R[BASE,m]
        P("   %-20s mean %6.2f%%  diff-vs-cur %+6.2f%%"%(lab,R[i,m].mean()*100,d.mean()*100))

P("\n\n########## 7) 5-SLOT CONSTRAINT ##########")
for which in ("opt","pes"):
    R2,L2,X2,N2=RES[(which,0.0)]
    P("-- %s --"%which)
    P("%-20s %8s %8s %8s %8s"%("rule","n_taken","mean%","sum%","uncons.mean%"))
    for lab,i in CAND.items():
        tk=A.slots(R2[i],t0,X2[i],5)
        P("%-20s %8d %8.2f %8.1f %8.2f"%(lab,len(tk),R2[i,tk].mean()*100,R2[i,tk].sum()*100,R2[i].mean()*100))

P("\n\n########## 8) FEE / EXTRA-FILL SENSITIVITY ##########")
P("Fees are proportional to notional, so splitting one exit into two does NOT raise fee cost")
P("in the base model. Row 'extra=0.10%' charges an ADDITIONAL 0.10%% of margin per extra fill")
P("(wider effective spread on the smaller clip).")
for which in ("opt","pes"):
    for lab,i in CAND.items():
        a=RES[(which,0.0)][0][i].mean()*100; b=RES[(which,0.001)][0][i].mean()*100
        P("%-4s %-20s extra=0: %6.2f%%   extra=0.10%%: %6.2f%%   cost %5.2f%%p"%(which,lab,a,b,a-b))

P("\n\n########## 9) RANDOM-ENTRY BASELINE (same symbols, random timing, same exit rules) ##########")
kr,Rr,Lr,Xr,Nr=A.evalall(rand,cfgs,which="opt")
rdays=np.array([r["t0"] for r in rand])//86400000
P("%-20s %10s %10s %10s"%("rule","signal mean%","random mean%","edge%"))
for lab,i in CAND.items():
    a=R[i].mean()*100; b=Rr[i].mean()*100
    P("%-20s %10.2f %10.2f %10.2f"%(lab,a,b,a-b))
P("(random n=%d)"%len(rand))

P("\n\n########## 10) LIQUIDATION MODEL NOTE ##########")
P("mmr assumed %.0f%% (leverageBracket needs an API key; 5%% is conservative -> nearer liq line)."%(E.MMR*100))
P("2x short isolated-equivalent liquidation at +%.2f%% price adverse."%E.LEVELS[-1])
P("Partial-close assumption: the liquidation line is held FIXED at the full-size (q=1) level.")
P("Under isolated margin with the freed margin left in the account, a partial close would push")
P("the liquidation price FURTHER away, so this is the conservative choice and it does not")
P("favour the staged rules. Because every stop line tested (<=40%) sits below the liquidation")
P("line, liquidation can only fire when a bar gaps straight through the stop.")

P("\n\n########## 11) MAE BUCKETS UNDER CURRENT RULE (checks the 'point of no return' claim) ##########")
mae=np.array([r["mae"] for r in real])
cur=RES[("opt",0.0)][0][BASE]
P("%-14s %6s %9s %9s %9s"%("MAE bucket","n","recover%","mean ret%","median%"))
for lo,hi in [(0,10),(10,20),(20,30),(30,40),(40,1000)]:
    m=(mae>=lo)&(mae<hi)
    if m.sum()==0: continue
    P("%-14s %6d %9.1f %9.2f %9.2f"%("%d-%d%%"%(lo,hi),m.sum(),(cur[m]>0).mean()*100,cur[m].mean()*100,np.median(cur[m])*100))

P("\n\n########## 12) EXIT-REASON MIX ##########")
for lab,i in CAND.items():
    R2,L2,X2,N2=RES[("opt",0.0)]
    P("%-20s avg fills %.2f  staged-fired %.1f%%"%(lab,N2[i].mean(),(N2[i]>1).mean()*100))
