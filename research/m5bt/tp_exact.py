"""익절 X% vs 손절 Y% — 봉내 순서를 정확히 따져 계산. 사용자 제안 검증용."""
import os,glob,numpy as np,pandas as pd
PQ='pq'; FD='fund'; BAR=300000; HOLD=576; LEV=2.0
FEE=0.0006; SLIP=0.0005; WIN_S=1754006400000; WIN_E=1785523200000
LB=84; VOLWIN=288; MINQV=3e6; NEW=30*24*3600*1000; COOL=12*3600*1000
TPS=[5.,10.,15.]; STOPS=[30.,40.]
def cumf(sym,t0,tx):
    p=os.path.join(FD,sym+'.npz')
    if not os.path.exists(p): return 0.0
    z=np.load(p); ft=z[z.files[0]]; fr=z[z.files[1]]
    cs=np.concatenate(([0.0],np.cumsum(fr)))
    return float(cs[np.searchsorted(ft,tx,'right')]-cs[np.searchsorted(ft,t0,'right')])
res={(tp,st):[] for tp in TPS for st in STOPS}
base=[]
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))
for k,s in enumerate(syms):
    z=np.load(os.path.join(PQ,s+'.npz'))
    t,o,h,l,c,qv=z['t'],z['o'],z['h'],z['l'],z['c'],z['qv']
    n=len(t)
    if n<LB+VOLWIN+700: continue
    ok=np.zeros(n,bool); ok[LB:]=(t[LB:]-t[:-LB])==LB*BAR
    ret=np.full(n,np.nan); ret[LB:]=(c[LB:]/c[:-LB]-1)*100
    cs=np.concatenate(([0.],np.cumsum(qv))); v24=np.full(n,np.nan); v24[VOLWIN-1:]=cs[VOLWIN:]-cs[:n-VOLWIN+1]
    sel=ok&(ret>=30)&(ret<40)&(v24>=MINQV)&((t-t[0])>=NEW)&(t>=WIN_S)&(t<WIN_E)
    idx=np.flatnonzero(sel); last=-1e18
    for i in idx:
        if t[i]-last<COOL: continue
        j=min(i+1+HOLD,n)
        if j-(i+1)<12: continue
        last=t[i]; P0=float(c[i])
        hh,ll,cc,bt=h[i+1:j],l[i+1:j],c[i+1:j],t[i+1:j]
        for tp in TPS:
            for st in STOPS:
                tpp=P0*(1-tp/100); stp=P0*(1+st/100)
                ex=None; kind=None; bi=len(cc)-1
                for b in range(len(cc)):
                    # 낙관 순서(o,l,h,c): 유리한 쪽을 먼저 본다 = 익절에 유리
                    hit_tp = ll[b]<=tpp
                    hit_st = hh[b]>=stp
                    if hit_tp and hit_st:
                        ex,kind,bi=tpp,'tp',b; break     # 낙관: 익절 우선
                    if hit_tp: ex,kind,bi=tpp,'tp',b; break
                    if hit_st: ex,kind,bi=stp,'stop',b; break
                if ex is None: ex,kind,bi=float(cc[-1]),'exp',len(cc)-1
                pnl=-LEV*(ex/P0-1)*100 - LEV*FEE*2*100 - (LEV*SLIP*100 if kind!='exp' else 0)
                pnl+= LEV*cumf(s,int(bt[0]),int(bt[bi]))*100
                res[(tp,st)].append(min(pnl,100) if pnl>-100 else -100)
        # 기준(현행): 손절40, 익절없음
        stp=P0*1.4; ex=None; kind=None; bi=len(cc)-1
        for b in range(len(cc)):
            if hh[b]>=stp: ex,kind,bi=stp,'stop',b; break
        if ex is None: ex,kind,bi=float(cc[-1]),'exp',len(cc)-1
        pnl=-LEV*(ex/P0-1)*100-LEV*FEE*2*100-(LEV*SLIP*100 if kind!='exp' else 0)+LEV*cumf(s,int(bt[0]),int(bt[bi]))*100
        base.append(max(pnl,-100))
    if (k+1)%200==0: print('  {}/{}'.format(k+1,len(syms)),flush=True)
b=np.array(base)
print()
print('신호 {}건'.format(len(b)))
print('현행(손절-40%, 익절 없음, 트레일링 제외): 평균 {:+.2f}%  중앙 {:+.2f}%  승률 {:.1f}%'.format(b.mean(),np.median(b),(b>0).mean()*100))
print()
print('{:>8} {:>8} {:>10} {:>10} {:>9}'.format('익절','손절','평균%','중앙%','승률%'))
for tp in TPS:
    for st in STOPS:
        a=np.array(res[(tp,st)])
        print('{:>7.0f}% {:>7.0f}% {:>10.2f} {:>10.2f} {:>8.1f}%'.format(tp,st,a.mean(),np.median(a),(a>0).mean()*100))
