import os,pickle,numpy as np
from scipy import stats
import engine as E, analyze as A
D=os.path.dirname(os.path.abspath(__file__))
dat=pickle.load(open(os.path.join(D,"events.pkl"),"rb"))
real=dat["real"]; rand=dat["rand"]
hold=np.array([r["hold"] for r in real]); days=np.array([r["t0"] for r in real])//86400000
cfgs=A.build_grid(); keys=list(cfgs)
BASE=keys.index((None,0.0,40.0,40.0)); MM=keys.index((12.0,0.5,20.0,20.0))
BEST=keys.index((8.0,0.7,40.0,40.0)); S20=keys.index((None,0.0,20.0,20.0))
CAND={"single-40 (current)":BASE,"single-20":S20,"MiniMax(12/50/->20)":MM,"best staged T8/R70/F40":BEST}
print("### FUNDING DECOMPOSITION ###")
for which in ("opt","pes"):
    print("-- %s (%s) --"%(which,"low-first" if which=="opt" else "high-first"))
    Rf=np.zeros((len(keys),len(real))); Rn=np.zeros_like(Rf)
    for j,rec in enumerate(real):
        se=rec[which]
        for i in CAND.values():
            T1,Rr,S,F=keys[i]
            Rf[i,j]=E.evaluate(se,T1,Rr,S,F,funding_fn=E.funding)["ret"]
            Rn[i,j]=E.evaluate(se,T1,Rr,S,F,funding_fn=None)["ret"]
    print("%-24s %11s %11s %11s"%("rule","with fund%","no fund%","funding %p"))
    for lab,i in CAND.items():
        print("%-24s %11.2f %11.2f %11.2f"%(lab,Rf[i].mean()*100,Rn[i].mean()*100,(Rf[i]-Rn[i]).mean()*100))
    print("  paired diffs vs current, FUNDING EXCLUDED:")
    for msk,ml in ((~hold,"TRAIN"),(hold,"HOLDOUT"),(np.ones(len(real),bool),"ALL")):
        for lab,i in CAND.items():
            if i==BASE: continue
            d=Rn[i,msk]-Rn[BASE,msk]; t,p=stats.ttest_rel(Rn[i,msk],Rn[BASE,msk])
            ci,_=A.day_boot(d,days[msk],nrep=2000)
            print("   %-8s %-24s %7.2f%% vs %7.2f%%  diff %+6.2f%% [%6.2f,%6.2f] t=%5.2f p=%.4f"%(
                ml,lab,Rn[i,msk].mean()*100,Rn[BASE,msk].mean()*100,d.mean()*100,ci[0]*100,ci[1]*100,t,p))
