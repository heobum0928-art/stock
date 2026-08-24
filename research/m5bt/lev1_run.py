"""PREREG_LEV1.md 실행 — 레버리지 1배 + 손절 명목 -80% vs 현행 2배/-40%. 짝비교."""
import os,glob,json,hashlib,pickle
import numpy as np
import engine as E, signals as S, build as BU

D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq')
HOLD_BARS=576
LEVELS_A=[8.,12.,16.,20.,25.,30.,40., (1-2.0*E.MMR)/(2.0*(1+E.MMR))*100]      # 42.857
LEVELS_B=[16.,24.,32.,40.,50.,60.,80., (1-1.0*E.MMR)/(1.0*(1+E.MMR))*100]     # 90.476
def cfg(lev,levels):
    E.LEV=lev; E.LEVELS=levels; E.IDX={v:i for i,v in enumerate(levels)}; E.LIQ_IDX=len(levels)-1

def mk(sym,i,t,o,h,l,c,levels):
    """build.make와 동일하되 levels를 명시 전달(scan의 기본인자는 정의시점에 묶여 있음)."""
    P0=float(c[i]); j=min(i+1+HOLD_BARS,len(c))
    if j-(i+1)<12: return None
    sl=slice(i+1,j); hh,ll,oo,cc,bt=h[sl],l[sl],o[sl],c[sl],t[sl]
    cf=BU.cumfund_for(sym,int(t[i]),bt).astype(np.float32)
    f,tr,ex,mae,mfe=E.scan(hh,ll,oo,cc,P0,opt=True,levels=levels)
    se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,len(cc)); se.cumfund=cf
    return se

syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))
rows=[]
for n_,s in enumerate(syms):
    try: sg,arr=S.sigs_for(s)
    except Exception: continue
    if not sg: continue
    t,o,h,l,c,qv=arr
    for (i,ts,px,ret,v24) in sg:
        cfg(2.0,LEVELS_A); sa=mk(s,i,t,o,h,l,c,LEVELS_A)
        if sa is None: continue
        ra=E.evaluate(sa,None,0.0,40.0,40.0,funding_fn=E.funding)
        cfg(1.0,LEVELS_B); sb=mk(s,i,t,o,h,l,c,LEVELS_B)
        rb=E.evaluate(sb,None,0.0,80.0,80.0,funding_fn=E.funding)
        rows.append((s,int(ts),BU.holdout(s),ra['ret'],rb['ret'],ra['liq'],rb['liq'],
                     ra['kind']==('stop'),rb['kind']==('stop')))
    if (n_+1)%150==0: print('  {}/{} 누적 {}'.format(n_+1,len(syms),len(rows)),flush=True)
a=np.array(rows,dtype=[('sym','U15'),('t0','i8'),('hold','?'),('A','f8'),('B','f8'),
                       ('liqA','?'),('liqB','?'),('stopA','?'),('stopB','?')])
np.save(os.path.join(D,'lev1.npy'),a)
print('n={}  A평균 {:+.3f}%  (재현목표 -4.798)'.format(len(a),a['A'].mean()*100),flush=True)
