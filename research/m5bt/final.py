import numpy as np, json, os, pickle
from scipy import stats
exec(open('baseline.py').read().split('# ---- signals')[0])  # reuse loaders/constants
def sim2(O,H,L,C,ei,P0,mode):
    """mode: 'opt' fill=stop_px | 'mid' fill=mid(stop,high) | 'pes' liq-first"""
    stop_px=P0*1.40; liq_px=1.5*P0/(1+MMR); mfe=P0
    last=min(N-1,ei+HOLD_BARS)
    for i in range(ei,last+1):
        h=H[i]
        if np.isnan(h): continue
        trail=mfe+0.10*P0 if (1-mfe/P0)*100>=TRAIL_TRIG else np.inf
        if h>=stop_px:
            if mode=='pes' and h>=liq_px: return None,i,'liq'
            if mode=='opt': fill=max(stop_px,O[i])
            else: fill=max(stop_px,O[i],(stop_px+min(h,liq_px))/2)
            if fill>=liq_px: return None,i,'liq'
            return fill,i,'stop'
        if h>=trail: return (max(trail,O[i]) if not np.isnan(O[i]) else trail),i,'trail'
        if L[i]<mfe: mfe=L[i]
    j=last
    while j>ei and np.isnan(O[j]): j-=1
    return (O[j] if not np.isnan(O[j]) else C[ei]),j,('expiry' if last==ei+HOLD_BARS else 'dataend')

D=pickle.load(open('signals.pkl','rb')); SIGS=D['sigs']
bysym={}
for s in SIGS: bysym.setdefault(s['sym'],[]).append(s)
DEL=[0,3,6,12]
res={(m,d):[] for m in ('opt','mid','pes') for d in DEL}
gap=[]; keys=[]
for k,sym in enumerate(sorted(bysym)):
    O,H,L,C,QV=regrid(*load(sym))
    for s in bysym[sym]:
        ok=all(not np.isnan(O[s['sig_i']+1+d]) for d in DEL if s['sig_i']+1+d<N)
        if not ok or s['sig_i']+1+12>=N: continue
        keys.append((sym,s['ts'],s['btc30']))
        for d in DEL:
            ei=s['sig_i']+1+d; P0=O[ei]
            for m in ('opt','mid','pes'):
                px,xi,kd=sim2(O,H,L,C,ei,P0,m)
                res[(m,d)].append(pnl(sym,P0,px,ei,xi,kd))
            if d==0:
                px,xi,kd=sim2(O,H,L,C,ei,P0,'opt')
                if kd=='stop': gap.append(max(0.0,(H[xi]-P0*1.40)/P0*100))
    if k%150==0: print(k,flush=True)
for m in ('opt','mid','pes'):
    for d in DEL: res[(m,d)]=np.array(res[(m,d)])*100
n=len(res[('opt',0)]); print('paired n =',n)
LBL={0:'T+0',3:'T+15',6:'T+30',12:'T+60'}
for m,nm in (('opt','OPTIMISTIC stop fill'),('mid','MID stop fill'),('pes','PESSIMISTIC (liq-first)')):
    print(f"\n--- {nm} ---")
    for d in DEL:
        v=res[(m,d)]
        print(f"  {LBL[d]:<5} mean={v.mean():+7.2f}%  med={np.median(v):+6.2f}%  win={(v>0).mean()*100:5.1f}%")
    for a in (3,6,12):
        dd=res[(m,0)]-res[(m,a)]; t,p=stats.ttest_rel(res[(m,0)],res[(m,a)])
        ci=stats.t.interval(0.95,n-1,loc=dd.mean(),scale=stats.sem(dd))
        print(f"  paired T+0 - {LBL[a]}: {dd.mean():+.3f}%p CI[{ci[0]:+.2f},{ci[1]:+.2f}] t={t:+.3f} p={p:.4f}")
g=np.array(gap); print(f"\nstop-exit intrabar overshoot beyond +40%: n={len(g)} median={np.median(g):.2f}%p "
      f"p90={np.percentile(g,90):.2f}%p max={g.max():.1f}%p ; frac spiking past liq line(+42.9%)={(g>2.86).mean()*100:.1f}%")
pickle.dump(dict(res={k:v for k,v in res.items()},keys=keys),open('final_res.pkl','wb'))
