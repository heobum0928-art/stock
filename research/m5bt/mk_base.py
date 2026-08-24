import os,pickle,json
import numpy as np, engine as E
D=os.path.dirname(os.path.abspath(__file__))
dat=pickle.load(open(os.path.join(D,"events.pkl"),"rb"))
out={}
for tag in ("real","rand"):
    recs=dat[tag]
    n=len(recs)
    d={k:np.zeros(n) for k in ("ret_opt","ret_pes","ret_opt_nf","ret_pes_nf","mae","mfe","t0","xt_opt","ret7h")}
    kind=[]; sym=[]; reg=[]; deli=np.zeros(n,bool); hold=np.zeros(n,bool); liq=np.zeros(n,bool)
    for j,r in enumerate(recs):
        a=E.evaluate(r["opt"],None,0.0,40.0,40.0,funding_fn=E.funding)
        b=E.evaluate(r["pes"],None,0.0,40.0,40.0,funding_fn=E.funding)
        a2=E.evaluate(r["opt"],None,0.0,40.0,40.0,funding_fn=None)
        b2=E.evaluate(r["pes"],None,0.0,40.0,40.0,funding_fn=None)
        d["ret_opt"][j]=a["ret"]; d["ret_pes"][j]=b["ret"]
        d["ret_opt_nf"][j]=a2["ret"]; d["ret_pes_nf"][j]=b2["ret"]
        d["mae"][j]=r["mae"]; d["mfe"][j]=r["mfe"]; d["t0"][j]=r["t0"]
        d["xt_opt"][j]=a["exit_ts"]; d["ret7h"][j]=r.get("ret7h",np.nan)
        kind.append(a["kind"]); sym.append(r["sym"]); reg.append(r["regime"])
        deli[j]=r["delisted"]; hold[j]=r["hold"]; liq[j]=a["liq"]
    np.savez(os.path.join(D,"base_%s.npz"%tag), sym=np.array(sym), kind=np.array(kind),
             reg=np.array(reg), deli=deli, hold=hold, liq=liq, **d)
    print(tag,n,"mean opt %.3f pes %.3f"%(d["ret_opt"].mean()*100, d["ret_pes"].mean()*100))
