"""역행 -X%(증거금)를 밟은 뒤 실제로 어떻게 끝났는가.
검증된 엔진 사용. 확장 레벨로 '터치 시점'을 얻고, 최종 결과는 현행 규칙(F=40) 그대로."""
import os,glob
import numpy as np
import engine as E, signals as S, build as BU
D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq'); HOLD=576
LIQ=(1-2.0*E.MMR)/(2.0*(1+E.MMR))*100
PROBE=[5.,10.,12.5,15.,17.5,20.,25.,30.,35.,37.5]   # 명목 % → 증거금 10~75%
LEVELS=sorted(set(PROBE+[8.,12.,16.,20.,25.,30.,40.]))+[LIQ]
E.LEVELS=LEVELS; E.IDX={v:i for i,v in enumerate(LEVELS)}; E.LIQ_IDX=len(LEVELS)-1
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))
rows=[]
for n_,s in enumerate(syms):
    try: sg,arr=S.sigs_for(s)
    except Exception: continue
    if not sg: continue
    t,o,h,l,c,qv=arr
    for (i,ts,px,ret,v24) in sg:
        P0=float(c[i]); j=min(i+1+HOLD,len(c))
        if j-(i+1)<12: continue
        sl=slice(i+1,j); hh,ll,oo,cc,bt=h[sl],l[sl],o[sl],c[sl],t[sl]
        cf=BU.cumfund_for(s,int(t[i]),bt).astype(np.float32)
        f,tr,ex,mae,mfe=E.scan(hh,ll,oo,cc,P0,opt=True,levels=LEVELS)
        se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,len(cc)); se.cumfund=cf
        r=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
        xb=r['exit_bar']
        touch=[(f[E.IDX[p]] is not None and f[E.IDX[p]][1]<=xb) for p in PROBE]
        rows.append(tuple([s,int(ts),r['ret'],r['liq']]+touch))
    if (n_+1)%200==0: print('  {}/{} {}'.format(n_+1,len(syms),len(rows)),flush=True)
dt=[('sym','U15'),('t0','i8'),('ret','f8'),('liq','?')]+[('p%d'%int(p*10),'?') for p in PROBE]
a=np.array(rows,dtype=dt); np.save(os.path.join(D,'ddown2.npy'),a)
print('n={}  평균 {:+.3f}%  (재현목표 -4.798)'.format(len(a),a['ret'].mean()*100),flush=True)
