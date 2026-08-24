import sys, os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, lib, datetime as dt
import sweep_volume as SV
syms=lib.symbols()
for HALF in ('disc','hold'):
    T=[];S=[];R24=[];R48=[];C2=[];C4=[]
    for si,s in enumerate(syms):
        d=lib.load(s); n=len(d['t']); m,rets=lib.fwd_returns(d,HALF)
        T.append(d['t']); S.append(np.full(n,si,np.int32))
        for k,acc in (('24h',R24),('48h',R48)):
            r=rets[k].copy(); r[~m]=np.nan; acc.append(r)
        F,_,_=SV.build_features(d); C2.append(F['ats288>=1.5'])
        mn=pd.Series(d['l'].astype(float)).rolling(48,min_periods=48).min().to_numpy()
        C4.append((d['c']/mn-1.0)*100.0>50.0)
    t=np.concatenate(T); sid=np.concatenate(S)
    r24=lib.short_of(np.concatenate(R24)); r48=lib.short_of(np.concatenate(R48))
    c2=np.concatenate(C2); c4=np.concatenate(C4)
    day=(t//86400000)
    g=lambda x: dt.datetime.utcfromtimestamp(x*86400).strftime('%m-%d')
    print('===',HALF,'===')
    for nm,sig,ret in (('후보2 ats288>=1.5 숏48h',c2,r48),('후보4 DU48>+50% 숏24h',c4,r24)):
        m=np.asarray(sig,bool)&np.isfinite(ret)
        d_=day[m]; s_=sid[m]; r_=ret[m]
        ud=np.unique(d_)
        contrib={u:r_[d_==u].sum() for u in ud}
        top=sorted(contrib,key=lambda k:-contrib[k])[:3]
        print('  {:26s} n={:5d}  종목 {:3d}  날짜 {:3d}  평균 {:+7.2f}'.format(nm,m.sum(),len(np.unique(s_)),len(ud),r_.mean()))
        print('      상위3일 기여 {:.0f}% | 상위3종목 기여 {:.0f}%'.format(
            sum(contrib[x] for x in top)/r_.sum()*100,
            sum(sorted([r_[s_==u].sum() for u in np.unique(s_)],reverse=True)[:3])/r_.sum()*100))
        print('      가장 기여 큰 날: {}'.format(', '.join(g(x) for x in top)))
