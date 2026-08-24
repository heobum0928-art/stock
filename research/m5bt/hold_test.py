import os,glob,numpy as np
from scipy import stats
import signals as S, engine as E, build as B, analyze as A
D=os.path.dirname(os.path.abspath(__file__))
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(D,"pq","*.npz")))
HOLDS={"12h":144,"24h":288,"48h":576}
RULES={"single-40":(None,0,40,40),"T8/R70/F40":(8.0,0.7,40.0,40.0),"single-20":(None,0,20,20)}
res={(h,r,w):[] for h in HOLDS for r in RULES for w in ("opt","pes")}
days=[]
for s in syms:
    try: sg,arrs=S.sigs_for(s)
    except Exception: continue
    if not sg: continue
    t,o,h_,l,c,qv=arrs
    for (i,ts,px,ret,v) in sg:
        P0=float(c[i]); ok=False
        cur={}
        for hn,hb in HOLDS.items():
            j=min(i+1+hb,len(c))
            if j-(i+1)<12: continue
            sl=slice(i+1,j); bt=t[sl]
            cf=B.cumfund_for(s,int(t[i]),bt).astype(np.float32)
            for w,optf in (("opt",True),("pes",False)):
                f,tr,ex,mae,mfe=E.scan(h_[sl],l[sl],o[sl],c[sl],P0,opt=optf)
                se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,j-i-1); se.cumfund=cf
                for rn,args in RULES.items():
                    cur[(hn,rn,w)]=E.evaluate(se,*args,funding_fn=E.funding)["ret"]
            ok=True
        if ok and len(cur)==len(res):
            for k,v2 in cur.items(): res[k].append(v2)
            days.append(int(t[i])//86400000)
days=np.array(days)
print("n =",len(days))
print("%-12s %-12s %10s %10s"%("hold","rule","low-first%","high-first%"))
for hn in HOLDS:
    for rn in RULES:
        a=np.array(res[(hn,rn,"opt")]); b=np.array(res[(hn,rn,"pes")])
        print("%-12s %-12s %10.2f %10.2f"%(hn,rn,a.mean()*100,b.mean()*100))
print("\npaired: 48h single-40 vs alternatives (low-first)")
base=np.array(res[("48h","single-40","opt")])
for hn in HOLDS:
    for rn in RULES:
        if hn=="48h" and rn=="single-40": continue
        a=np.array(res[(hn,rn,"opt")]); d=a-base
        t_,p=stats.ttest_rel(a,base); ci,_=A.day_boot(d,days,nrep=2000)
        print("  %-6s %-12s diff %+6.2f%% [%6.2f,%6.2f] t=%5.2f p=%.4f"%(hn,rn,d.mean()*100,ci[0]*100,ci[1]*100,t_,p))
