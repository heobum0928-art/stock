"""Build per-signal event objects (both intrabar orderings) + funding + regime + holdout."""
import os, json, glob, hashlib, pickle, sys
import numpy as np
import engine as E
from signals import sigs_for, load, LOOKBACK, VOLWIN, MIN_QV, NEWLIST_MS, WIN_S, WIN_E

D = os.path.dirname(os.path.abspath(__file__))
PQ = os.path.join(D,"pq"); FD = os.path.join(D,"fund")
HOLD_BARS = 576
RNG = np.random.default_rng(20260822)
N_RANDOM = 3

def holdout(sym):
    return int(hashlib.md5(sym.encode()).hexdigest(), 16) % 4 == 0

def cumfund_for(sym, t0, bt):
    p = os.path.join(FD, sym+".npz")
    if not os.path.exists(p): return np.zeros(len(bt), np.float64)
    z = np.load(p); ft = z[z.files[0]]; fr = z[z.files[1]]
    cs = np.concatenate(([0.0], np.cumsum(fr)))
    lo = np.searchsorted(ft, t0, side="right")
    hi = np.searchsorted(ft, bt, side="right")
    return cs[hi] - cs[lo]

def eligible_mask(t,o,h,l,c,qv):
    n=len(t); ms=300000
    ok_vw=np.zeros(n,bool); ok_vw[VOLWIN-1:]=(t[VOLWIN-1:]-t[:n-VOLWIN+1])==(VOLWIN-1)*ms
    cs=np.concatenate(([0.0],np.cumsum(qv)))
    vol24=np.full(n,np.nan); vol24[VOLWIN-1:]=cs[VOLWIN:]-cs[:n-VOLWIN+1]
    age=(t-t[0])>=NEWLIST_MS
    inwin=(t>=WIN_S)&(t<WIN_E)
    fwd=np.zeros(n,bool); fwd[:n-HOLD_BARS]=True
    return inwin & ok_vw & age & (vol24>=MIN_QV) & fwd

def make(sym, i, t,o,h,l,c,qv, btc_ret, tag):
    P0=float(c[i]); j=min(i+1+HOLD_BARS, len(c))
    if j-(i+1) < 12: return None
    sl=slice(i+1,j)
    hh=h[sl]; ll=l[sl]; oo=o[sl]; cc=c[sl]; bt=t[sl]
    cf = cumfund_for(sym,int(t[i]),bt).astype(np.float32)
    recs={}
    for opt in (True,False):
        f,tr,ex,mae,mfe = E.scan(hh,ll,oo,cc,P0,opt=opt)
        se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,len(cc))
        se.cumfund = cf
        recs[opt]=se
    return {"sym":sym,"t0":int(t[i]),"P0":P0,"opt":recs[True],"pes":recs[False],
            "mae":recs[True].mae,"mfe":recs[True].mfe,
            "hold":holdout(sym),"regime":btc_ret,"tag":tag,
            "truncated": (j-(i+1)) < HOLD_BARS}

def main():
    syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,"*.npz")))
    trading=set(json.load(open(os.path.join(D,"trading_syms.json"))))
    # BTC regime
    bt_t,_,_,_,bt_c,_ = load("BTCUSDT")
    W=30*288
    btcret=np.full(len(bt_c),np.nan); btcret[W:]=bt_c[W:]/bt_c[:-W]-1
    def regime_at(ts):
        k=np.searchsorted(bt_t,ts,side="right")-1
        if k<0 or k>=len(btcret) or not np.isfinite(btcret[k]): return "na"
        r=btcret[k]
        return "bull" if r>0.10 else ("bear" if r<-0.10 else "chop")
    recs=[]; rrecs=[]
    nsym=0; ndel=0; ndel_sig=0; nsig_del=0
    for s in syms:
        try:
            sg, arrs = sigs_for(s)
        except Exception as ex:
            print("ERR",s,ex); continue
        if sg is None: continue
        t,o,h,l,c,qv = arrs
        nsym+=1
        deli = s not in trading
        if deli: ndel+=1
        if not sg: continue
        if deli: ndel_sig+=1; nsig_del+=len(sg)
        elig=None
        for (i,ts,px,ret,v24) in sg:
            r=make(s,i,t,o,h,l,c,qv,regime_at(ts),"real")
            if r is None: continue
            r["ret7h"]=ret; r["delisted"]=deli
            recs.append(r)
            if elig is None:
                elig=np.nonzero(eligible_mask(t,o,h,l,c,qv))[0]
            if len(elig)>0:
                for _ in range(N_RANDOM):
                    k=int(RNG.integers(0,len(elig)))
                    rr=make(s,int(elig[k]),t,o,h,l,c,qv,regime_at(int(t[elig[k]])),"rand")
                    if rr is not None:
                        rr["ret7h"]=np.nan; rr["delisted"]=deli
                        rrecs.append(rr)
        if nsym%50==0: print(nsym,s,len(recs),flush=True)
    meta={"symbols_with_data":nsym,"delisted_symbols":ndel,
          "delisted_with_signals":ndel_sig,"signals_from_delisted":nsig_del,
          "n_signals":len(recs),"n_random":len(rrecs)}
    print(json.dumps(meta,indent=1))
    return {"real":recs,"rand":rrecs,"meta":meta}

if __name__=="__main__":
    d=main()
    with open(os.path.join(D,"events.pkl"),"wb") as f:
        pickle.dump(d,f,protocol=4)
