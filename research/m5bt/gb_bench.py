"""반납(giveback) 벤치마크: 신호진입 vs 무작위진입.
단위: 전부 명목가(가격) 기준 %. ret_opt는 증거금 기준 분수이므로 /LEV*100.
반납 = MFE(명목%) - 최종수익(명목%)
"""
import numpy as np
LEV=2.0
def load(tag):
    z=np.load('base_%s.npz'%tag, allow_pickle=True)
    mfe=z['mfe'].astype(float)                 # 명목 % (호의적 최대)
    ret=z['ret_opt'].astype(float)/LEV*100     # 명목 %
    return dict(mfe=mfe, ret=ret, gb=mfe-ret, hold=z['hold'], sym=z['sym'],
                mae=z['mae'].astype(float), kind=z['kind'], liq=z['liq'])
R=load('real'); N=load('rand')

def line(name,d,m=None):
    m = np.ones(len(d['mfe']),bool) if m is None else m
    n=m.sum()
    if n==0: return f"{name:>22}  n=0"
    return (f"{name:>22}  n={n:5d}  MFE {d['mfe'][m].mean():6.2f}  "
            f"최종 {d['ret'][m].mean():7.2f}  반납 {d['gb'][m].mean():7.2f}"
            f"  반납/MFE {d['gb'][m].mean()/max(d['mfe'][m].mean(),1e-9):5.3f}")

print("=== 전체 (명목가 기준 %) ===")
print(line("신호진입", R)); print(line("무작위진입", N))
print()
print("=== MFE 구간별 짝맞춤 (같은 MFE에 도달한 건끼리) ===")
print(f"{'MFE구간':>12} | {'신호 n':>6} {'신호 최종':>9} {'신호 반납':>9} | {'무작위 n':>7} {'무작위 최종':>10} {'무작위 반납':>10} | {'최종 차이':>9}")
edges=[0,5,10,15,20,25,30,40,60,1e9]
rows=[]
for a,b in zip(edges[:-1],edges[1:]):
    mr=(R['mfe']>=a)&(R['mfe']<b); mn=(N['mfe']>=a)&(N['mfe']<b)
    if mr.sum()<10 or mn.sum()<10: continue
    dr=R['ret'][mr].mean(); dn=N['ret'][mn].mean()
    lbl=f"{a:.0f}~{b:.0f}" if b<1e8 else f"{a:.0f}+"
    rows.append((lbl,mr.sum(),dr,R['gb'][mr].mean(),mn.sum(),dn,N['gb'][mn].mean(),dr-dn))
    print(f"{lbl:>12} | {mr.sum():6d} {dr:9.2f} {R['gb'][mr].mean():9.2f} | "
          f"{mn.sum():7d} {dn:10.2f} {N['gb'][mn].mean():10.2f} | {dr-dn:9.2f}")
