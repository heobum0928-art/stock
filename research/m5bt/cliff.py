import numpy as np
z=np.load('base_real.npz',allow_pickle=True)
mae=z['mae'].astype(float); ret=z['ret_opt']*100
LIQ=42.857
hit40=mae>=40.0
print(f"전체 {len(mae)}건")
print(f"-40%에 닿은 거래: {hit40.sum()}건 ({hit40.mean()*100:.1f}%)")
went=(mae>=LIQ)
print(f"그 중 -42.86%(강제청산)까지 간 것: {went.sum()}건 = {went.sum()/hit40.sum()*100:.1f}%")
print(f"-40%에 닿고 청산은 면한 것: {(hit40&~went).sum()}건 = {(hit40&~went).sum()/hit40.sum()*100:.1f}%\n")
print("=== 역행폭 구간별: 한 발 더 밀릴 확률 ===")
for a in (10,20,30,35,38,40,41,42):
    h=mae>=a
    nxt=mae>=LIQ
    if h.sum()==0: continue
    print(f"  -{a:>2}%에 닿은 {h.sum():4d}건 중 강제청산까지 간 것 {nxt[h].sum():4d}건 = {nxt[h].mean()*100:5.1f}%")
print("\n=== 회복률(최종 플러스로 끝난 비율), 현행 규칙 기준 ===")
for a,b in ((0,10),(10,20),(20,30),(30,35),(35,40),(40,100)):
    m=(mae>=a)&(mae<b)
    if m.sum()<5: continue
    print(f"  역행 {a:>2}~{b:<3}%  n={m.sum():4d}  최종플러스 {(ret[m]>0).mean()*100:5.1f}%  평균 {ret[m].mean():+7.2f}%")
