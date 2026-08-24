"""손실의 출처 분해: 가격 vs 펀딩 vs 청산방식. 단위 전부 증거금 기준 %."""
import numpy as np
def L(tag):
    z=np.load('base_%s.npz'%tag, allow_pickle=True)
    return dict(ret=z['ret_opt']*100, nf=z['ret_opt_nf']*100, kind=z['kind'],
                mfe=z['mfe'].astype(float), mae=z['mae'].astype(float), liq=z['liq'])
R=L('real'); N=L('rand')
print("단위: 증거금 기준 % (레버리지 2배 반영)\n")
for nm,d in (("신호진입",R),("무작위진입",N)):
    fund=d['ret']-d['nf']
    print(f"{nm}  n={len(d['ret'])}")
    print(f"   최종         {d['ret'].mean():7.2f}%")
    print(f"   펀딩 제외 시 {d['nf'].mean():7.2f}%   <- 가격+비용")
    print(f"   펀딩 기여    {fund.mean():+7.2f}%p")
    print(f"   MAE(역행 최대, 명목%) {d['mae'].mean():6.2f}   MFE {d['mfe'].mean():6.2f}")
    ks,cs=np.unique(d['kind'],return_counts=True)
    for k,c in zip(ks,cs):
        m=d['kind']==k
        print(f"     {k:8s} {c:5d}건 ({c/len(m)*100:5.1f}%)  평균 {d['ret'][m].mean():8.2f}%  기여 {d['ret'][m].sum()/len(m):+7.2f}%p")
    print()
print("=== 차이(신호-무작위) ===")
print(f"  최종      {R['ret'].mean()-N['ret'].mean():+7.2f}%p")
print(f"  펀딩제외  {R['nf'].mean()-N['nf'].mean():+7.2f}%p")
print(f"  펀딩      {(R['ret']-R['nf']).mean()-(N['ret']-N['nf']).mean():+7.2f}%p")
print(f"  MAE       {R['mae'].mean()-N['mae'].mean():+7.2f} (명목%)")
