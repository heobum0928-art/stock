import numpy as np,json,pickle,requests
from scipy import stats
exec(open('baseline.py').read().split('# ---- signals')[0])
D=pickle.load(open('signals.pkl','rb')); SIGS=D['sigs']
bysym={}
for s in SIGS: bysym.setdefault(s['sym'],[]).append(s)
# universe composition
j=requests.get('https://fapi.binance.com/fapi/v1/exchangeInfo',timeout=20).json()
st={s['symbol']:s['status'] for s in j['symbols']}
KEEP=json.load(open('keep_syms.json'))
from collections import Counter
c=Counter(st.get(s,'REMOVED/DELISTED') for s in KEEP)
print('universe(728) status:',dict(c))
print('signal-producing symbols:',len(bysym))
c2=Counter(st.get(s,'REMOVED/DELISTED') for s in bysym)
print('  of which by status:',dict(c2))
# first-hour move after signal
mv=[]
for k,sym in enumerate(sorted(bysym)):
    O,H,L,C,QV=regrid(*load(sym))
    for s in bysym[sym]:
        i=s['sig_i']+1
        if i+12<N and not np.isnan(O[i]) and not np.isnan(O[i+12]):
            mv.append((O[i]-O[i+12])/O[i]*100)
mv=np.array(mv)
print(f"\nprice move in the 60 min AFTER signal (short-favourable = positive):")
print(f"  n={len(mv)} mean={mv.mean():+.3f}% median={np.median(mv):+.3f}% t={stats.ttest_1samp(mv,0).statistic:+.2f} p={stats.ttest_1samp(mv,0).pvalue:.4f}")
print(f"  => at 2x leverage that first hour is worth {2*mv.mean():+.3f}%p of margin")
r=pickle.load(open('final_res.pkl','rb'))['res']
v=r[('opt',0)]
mo=np.array([np.datetime64(int(s['ts']),'ms').astype('datetime64[M]') for s in SIGS])
print('\nmonthly (T+0, optimistic):')
for m in np.unique(mo):
    x=v[mo==m]; print(f"  {m}  n={len(x):>4} mean={x.mean():+7.2f}% sum={x.sum():+8.1f}%")
