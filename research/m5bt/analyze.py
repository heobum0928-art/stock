import os, json, pickle, sys, math
import numpy as np
from scipy import stats
import engine as E

D=os.path.dirname(os.path.abspath(__file__))
T1s=[8.0,12.0,16.0,20.0]; Rs=[0.3,0.5,0.7]; Ss=[20.0,25.0,30.0,None]; Fs=[20.0,25.0,30.0,40.0]

def build_grid():
    cfgs={}
    for F in Fs:
        cfgs[(None,0.0,F,F)]=("single-%g"%F)
    for T1 in T1s:
        for F in Fs:
            if T1>=F: continue
            for R in Rs:
                for S in Ss:
                    Seff = F if S is None else min(S,F)
                    if Seff<=T1: continue
                    k=(T1,R,Seff,F)
                    if k in cfgs: continue
                    cfgs[k]="T%g/R%g/S%g/F%g"%(T1,R*100,Seff,F)
    return cfgs

def evalall(recs, cfgs, which="opt", extra=0.0, use_fund=True):
    ff = E.funding if use_fund else None
    out={}
    keys=list(cfgs)
    n=len(recs)
    R=np.zeros((len(keys),n)); LIQ=np.zeros((len(keys),n),bool)
    XT=np.zeros((len(keys),n),np.int64); NF=np.zeros((len(keys),n),np.int8)
    for j,rec in enumerate(recs):
        se=rec[which]
        for i,k in enumerate(keys):
            T1,Rf,Seff,F=k
            r=E.evaluate(se,T1,Rf,Seff,F,extra_fill_cost=extra,funding_fn=ff)
            R[i,j]=r["ret"]; LIQ[i,j]=r["liq"]; XT[i,j]=r["exit_ts"]; NF[i,j]=r["nfills"]
    return keys,R,LIQ,XT,NF

def day_boot(diff, days, nrep=4000, seed=7):
    rng=np.random.default_rng(seed)
    ud,inv=np.unique(days,return_inverse=True)
    idx=[np.nonzero(inv==k)[0] for k in range(len(ud))]
    means=np.empty(nrep)
    for b in range(nrep):
        pick=rng.integers(0,len(ud),len(ud))
        sel=np.concatenate([idx[p] for p in pick])
        means[b]=diff[sel].mean()
    return np.percentile(means,[2.5,97.5]), (diff.mean()/means.std(ddof=1) if means.std(ddof=1)>0 else np.nan)

def slots(ret, t0, xt, nslots=5):
    order=np.argsort(t0)
    busy=[]; taken=[]
    for j in order:
        busy=[b for b in busy if b>t0[j]]
        if len(busy)<nslots:
            busy.append(xt[j]); taken.append(j)
    return np.array(taken)
