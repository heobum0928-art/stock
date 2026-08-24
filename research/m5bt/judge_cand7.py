import numpy as np, datetime as dt
rng=np.random.default_rng(20260824)
def L(t):
    z=np.load('cand7_%s.npz'%t,allow_pickle=True)
    day=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m-%d') for x in z['t0'].astype(float)])
    return dict(ret=z['l_ret'],price=z['l_price'],fund=z['l_fund'],liq=z['l_liq'],
                kind=z['l_kind'],sym=z['sym'],hold=z['hold'].astype(bool),day=day)
R,N=L('real'),L('rand')
print("="*66)
print("후보 7 재검산 — 같은 신호에 롱 (증거금 기준 %, 펀딩·수수료 포함)")
print("="*66)
for nm,d in (("신호 롱",R),("무작위 롱",N)):
    print(f"\n{nm}  n={len(d['ret'])}")
    print(f"  최종      {d['ret'].mean():+7.3f}%   중앙 {np.median(d['ret']):+7.2f}   승률 {(d['ret']>0).mean()*100:.1f}%")
    print(f"  가격 기여 {d['price'].mean():+7.3f}%p")
    print(f"  펀딩 기여 {d['fund'].mean():+7.3f}%p")
    print(f"  강제청산  {d['liq'].mean()*100:5.1f}%")
    ks,cs=np.unique(d['kind'],return_counts=True)
    print("  청산사유: "+"  ".join(f"{k} {c}({c/len(d['ret'])*100:.1f}%)" for k,c in zip(ks,cs)))

def boot(a,sa,b,sb,B=4000):
    ua,ub=np.unique(sa),np.unique(sb)
    ia={s:np.nonzero(sa==s)[0] for s in ua}; ib={s:np.nonzero(sb==s)[0] for s in ub}
    o=np.empty(B)
    for k in range(B):
        pa=rng.integers(0,len(ua),len(ua)); pb=rng.integers(0,len(ub),len(ub))
        A=np.concatenate([ia[ua[i]] for i in pa]); Bx=np.concatenate([ib[ub[i]] for i in pb])
        o[k]=a[A].mean()-b[Bx].mean()
    return o

print("\n"+"="*66); print("사전등록 판정 (PREREG_CAND7_RECHECK.md)"); print("="*66)
diff=R['ret'].mean()-N['ret'].mean()
bs=boot(R['ret'],R['sym'],N['ret'],N['sym'])
lo,hi=np.percentile(bs,[2.5,97.5])
print(f"\n[1차] 신호 롱 - 무작위 롱")
c1 = diff>0
print(f"  조건1 차이 > 0            : {diff:+.3f}%p  -> {'충족' if c1 else '미충족'}")
c2 = (lo>0) or (hi<0)
print(f"  조건2 부트스트랩 95%CI    : [{lo:+.3f}, {hi:+.3f}]  -> {'0 제외(충족)' if c2 else '0 포함(미충족)'}")
mh=R['hold']; nh=N['hold']
dh=R['ret'][mh].mean()-N['ret'][nh].mean()
c3 = np.sign(dh)==np.sign(diff) and diff!=0
print(f"  조건3 홀드아웃 부호 일치  : {dh:+.3f}%p (n={mh.sum()}/{nh.sum()})  -> {'충족' if c3 else '미충족'}")
mr=R['day']!='2025-10-11'; nr=N['day']!='2025-10-11'
dx=R['ret'][mr].mean()-N['ret'][nr].mean()
c4 = np.sign(dx)==np.sign(diff) and diff!=0
print(f"  조건4 10-11 제외 부호일치 : {dx:+.3f}%p (제외 {(~mr).sum()}/{(~nr).sum()}건)  -> {'충족' if c4 else '미충족'}")
print(f"\n  ==> 1차 관문: {'통과' if all([c1,c2,c3,c4]) else '미통과'}  ({sum([c1,c2,c3,c4])}/4)")

bs2=boot(R['ret'],R['sym'],np.zeros(1),np.array(['_']))
lo2,hi2=np.percentile(bs2,[2.5,97.5])
print(f"\n[2차] 신호 롱 자체 > 0")
print(f"  기대값 {R['ret'].mean():+.3f}%  95%CI [{lo2:+.3f}, {hi2:+.3f}]")
print(f"  ==> 2차 관문: {'통과' if R['ret'].mean()>0 and lo2>0 else '미통과'}")

print("\n[병기] 기존 기록 '이득이 전부 펀딩' 재현 여부")
print(f"  신호 롱: 가격 {R['price'].mean():+.3f} + 펀딩 {R['fund'].mean():+.3f} + 수수료 등 = 최종 {R['ret'].mean():+.3f}")
print(f"  무작위 롱: 가격 {N['price'].mean():+.3f} + 펀딩 {N['fund'].mean():+.3f} = 최종 {N['ret'].mean():+.3f}")
print(f"  펀딩 차이(신호-무작위): {R['fund'].mean()-N['fund'].mean():+.3f}%p")
print(f"  가격 차이(신호-무작위): {R['price'].mean()-N['price'].mean():+.3f}%p")
print(f"\n[병기] 슬롯5 월간(월 48건 페이스, 증거금 50): {R['ret'].mean()/100*50*48:+.1f} USDT/월")
