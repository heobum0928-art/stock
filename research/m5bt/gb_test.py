import numpy as np, datetime as dt
LEV=2.0
rng=np.random.default_rng(20260824)
def load(tag):
    z=np.load('base_%s.npz'%tag, allow_pickle=True)
    mfe=z['mfe'].astype(float); ret=z['ret_opt'].astype(float)/LEV*100
    t0=z['t0'].astype(float)
    day=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m-%d') for x in t0])
    return dict(mfe=mfe,ret=ret,gb=mfe-ret,sym=z['sym'],hold=z['hold'],day=day)
R=load('real'); N=load('rand')

def ratio(d,m): return d['gb'][m].sum()/d['mfe'][m].sum()   # 총반납/총MFE

def boot(d,m,B=4000):
    syms=np.unique(d['sym'][m]); idx={s:np.nonzero(m&(d['sym']==s))[0] for s in syms}
    out=np.empty(B)
    for b in range(B):
        pick=rng.integers(0,len(syms),len(syms))
        ii=np.concatenate([idx[syms[k]] for k in pick])
        out[b]=d['gb'][ii].sum()/d['mfe'][ii].sum()
    return out

allR=np.ones(len(R['mfe']),bool); allN=np.ones(len(N['mfe']),bool)
print("[1] 반납비율(총반납/총MFE), 종목 클러스터 부트스트랩 4000회")
br=boot(R,allR); bn=boot(N,allN)
d=br-bn
print("  신호 %.4f  [%.4f, %.4f]"%(ratio(R,allR),np.percentile(br,2.5),np.percentile(br,97.5)))
print("  무작위 %.4f  [%.4f, %.4f]"%(ratio(N,allN),np.percentile(bn,2.5),np.percentile(bn,97.5)))
print("  차이 %.4f  95%%CI [%.4f, %.4f]  p(양측) %.3f"%(d.mean(),np.percentile(d,2.5),np.percentile(d,97.5),
      2*min((d<=0).mean(),(d>=0).mean())))

print("\n[2] 2025-10-11 제외 시")
for nm,dd,mm in (("신호",R,allR),("무작위",N,allN)):
    m2=mm&(dd['day']!='2025-10-11')
    print("  %s 전체 %.4f -> 제외 %.4f (제외건수 %d)"%(nm,ratio(dd,mm),ratio(dd,m2),(mm&~m2).sum()))

print("\n[3] 홀드아웃(hold=True)만")
for nm,dd in (("신호",R),("무작위",N)):
    m3=dd['hold'].astype(bool)
    print("  %s n=%d 반납비율 %.4f  MFE %.2f  최종 %.2f"%(nm,m3.sum(),ratio(dd,m3),dd['mfe'][m3].mean(),dd['ret'][m3].mean()))

print("\n[4] 실거래 48건 주장 재현: 신호진입 2,399건의 합계")
print("  MFE합 %.1f%%  최종합 %.1f%%  반납합 %.1f%%p"%(R['mfe'].sum(),R['ret'].sum(),R['gb'].sum()))
print("  건당: MFE %.2f  최종 %.2f  반납 %.2f"%(R['mfe'].mean(),R['ret'].mean(),R['gb'].mean()))
print("  무작위 건당: MFE %.2f  최종 %.2f  반납 %.2f"%(N['mfe'].mean(),N['ret'].mean(),N['gb'].mean()))
