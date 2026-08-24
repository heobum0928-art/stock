import numpy as np
z=np.load('base_real.npz',allow_pickle=True)
mae=z['mae'].astype(float); ret=z['ret_opt']*100
MMR=0.05
def liq(L): return (1-L*MMR)/(L*(1+MMR))*100
print("명목(가격) 기준 건당 기대값: %.2f%%  <- 이게 음수면 레버리지를 곱할수록 나빠진다\n"%(ret.mean()/2))
print(f"{'레버리지':>8} {'강제청산 역행':>13} {'청산되는 신호':>14} {'그 구간 회복률':>15}")
for L in (1.0,1.5,2.0,3.0,5.0,10.0):
    a=liq(L); n=(mae>=a).sum()
    # 그 선을 넘은 거래들이 현행 규칙에서 결국 플러스로 끝난 비율
    m=mae>=a
    rec=(ret[m]>0).mean()*100 if m.sum() else float('nan')
    print(f"{L:7.1f}배 {a:12.2f}% {n:8d}건 ({n/len(mae)*100:4.1f}%) {rec:13.1f}%")
print("\n※ '회복률' = 그 역행폭에 닿았던 거래가 현행 규칙에서 결국 플러스로 끝난 비율.")
print("   레버리지를 올리면 이 거래들이 '회복하기 전에' 강제청산된다.")
print("\n=== 참고: 역행폭 도달 분포 ===")
for a in (10,15,20,25,27,30,40,43,50,60,90):
    print(f"  역행 {a:>2}% 도달: {(mae>=a).sum():4d}건 ({(mae>=a).mean()*100:5.1f}%)")
