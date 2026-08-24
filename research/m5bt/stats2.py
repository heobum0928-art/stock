import pickle,numpy as np
from scipy import stats
B=pickle.load(open('baseline.pkl','rb'))
sig=B['sig']; base=B['base']; bnf=B['base_nofilt']
def desc(rows,nm):
    v=np.array([r['pnl'] for r in rows])*100
    k=[r['kind'] for r in rows]; n=len(v)
    print(f"{nm:<28} n={n:>6} mean={v.mean():+7.2f}%  med={np.median(v):+7.2f}%  win={(v>0).mean()*100:5.1f}%  "
          f"liq={k.count('liq')/n*100:5.2f}%  stop={k.count('stop')/n*100:5.1f}%  trail={k.count('trail')/n*100:5.1f}%")
    return v
print('=== realistic stop fill (gap-through -> fill at bar open; fill beyond liq line -> -100%) ===')
vs=desc(sig,'SIGNAL T+0')
vb=desc(base,'RANDOM (regime-matched)')
vn=desc(bnf,'RANDOM (no regime filter)')

def boot(a,b,B=20000,seed=1):
    rng=np.random.default_rng(seed)
    d=np.empty(B)
    for i in range(B):
        d[i]=rng.choice(a,len(a),True).mean()-rng.choice(b,len(b),True).mean()
    return d
d=boot(vs,vb)
print(f"\nSIGNAL - RANDOM(regime-matched) = {vs.mean()-vb.mean():+.2f}%p  bootstrap 95%CI [{np.percentile(d,2.5):+.2f},{np.percentile(d,97.5):+.2f}]  p_two_sided={2*min((d>0).mean(),(d<0).mean()):.4f}")
t,p=stats.ttest_ind(vs,vb,equal_var=False); print(f"Welch t={t:+.3f} p={p:.4f}")
d2=boot(vs,vn); print(f"SIGNAL - RANDOM(unfiltered)     = {vs.mean()-vn.mean():+.2f}%p  95%CI [{np.percentile(d2,2.5):+.2f},{np.percentile(d2,97.5):+.2f}]")
print(f"\nSIGNAL mean vs 0: t={stats.ttest_1samp(vs,0).statistic:+.3f} p={stats.ttest_1samp(vs,0).pvalue:.4f}")
days=np.array([r['ts']//86400000 for r in sig]); ud=np.unique(days)
dm=np.array([vs[days==u].mean() for u in ud])
print(f"day-clustered: n_days={len(ud)} mean={dm.mean():+.3f}% t={stats.ttest_1samp(dm,0).statistic:+.3f} p={stats.ttest_1samp(dm,0).pvalue:.4f}")
print(f"total sum of per-trade returns (equal size): {vs.sum():+.1f}%  -> per trade {vs.mean():+.2f}%")
# tail
srt=np.sort(vs); print('worst5:',np.round(srt[:5],1),' best5:',np.round(srt[-5:],1))
print('\n=== regime split, realistic fill ===')
for lo,hi,nm in ((0.10,9,'bull'),(-9,-0.10,'bear'),(-0.10,0.10,'side')):
    v=np.array([r['pnl'] for r in sig if lo<r['btc30']<=hi])*100
    print(f"{nm:<6} n={len(v):>5} mean={v.mean():+7.2f}% med={np.median(v):+6.2f}% win={(v>0).mean()*100:.1f}%")
# half-sample stability
h=len(sig)//2
print(f"\n1st half mean {vs[:h].mean():+.2f}%  2nd half mean {vs[h:].mean():+.2f}%")
