"""PREREG_TINY_TP.md 실행. 손절·청산·만기·펀딩은 엔진 결과 그대로, 익절 분기만 추가."""
import os,glob
import numpy as np
import engine as E, signals as S, build as BU
D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq'); HOLD=576
LIQ=(1-2.0*E.MMR)/(2.0*(1+E.MMR))*100
LEVELS=[8.,12.,16.,20.,25.,30.,40.,LIQ]
E.LEVELS=LEVELS; E.IDX={v:i for i,v in enumerate(LEVELS)}; E.LIQ_IDX=len(LEVELS)-1
TPS=[(2.0,1.0),(3.0,1.5)]          # (증거금%, 명목%)
ENTRIES=[((30.,40.),'cur_30_40'),((15.,40.),'wide_15_40')]
out={}
for (lo,hi),ename in ENTRIES:
    S.PUMP_LO,S.PUMP_HI=lo,hi
    rows=[]
    for n_,p in enumerate(sorted(glob.glob(os.path.join(PQ,'*.npz')))):
        s=os.path.basename(p)[:-4]
        try: sg,arr=S.sigs_for(s)
        except Exception: continue
        if not sg: continue
        t,o,h,l,c,qv=arr
        for (i,ts,px0,ret7,v24) in sg:
            P0=float(c[i]); j=min(i+1+HOLD,len(c))
            if j-(i+1)<12: continue
            sl=slice(i+1,j); hh,ll,oo,cc,bt=h[sl],l[sl],o[sl],c[sl],t[sl]
            cf=BU.cumfund_for(s,int(t[i]),bt).astype(np.float32)
            f,tr,ex,mae,mfe=E.scan(hh,ll,oo,cc,P0,opt=True,levels=LEVELS)
            se=E.SigEvents(f,tr,ex,mae,mfe,P0,int(t[i]),bt,len(cc)); se.cumfund=cf
            base=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
            rec=[s,int(ts),bool(BU.holdout(s)),base['ret']]
            for mg,nomi in TPS:
                tpp=P0*(1-nomi/100)
                hit=np.flatnonzero(ll<=tpp)
                if len(hit)==0 or hit[0]>base['exit_bar']:
                    rec.append(base['ret']); continue
                b=int(hit[0])
                fill=min(float(oo[b]),tpp) if float(oo[b])<=tpp else tpp   # 갭이면 시가
                r=-E.LEV*E.FEE_SIDE                       # 진입 수수료
                r+=-E.LEV*(fill/P0-1)                     # 가격
                r+=-E.LEV*E.FEE_SIDE                      # 청산 수수료(지정가, 추가슬립 없음)
                r+=E.LEV*float(cf[b])                     # 펀딩
                rec.append(max(r,-1.0))
            rows.append(tuple(rec))
        if (n_+1)%250==0: print('  {} {}/805 {}'.format(ename,n_+1,len(rows)),flush=True)
    dt=[('sym','U15'),('t0','i8'),('hold','?'),('base','f8')]+[('tp%d'%int(m),'f8') for m,_ in TPS]
    a=np.array(rows,dtype=dt); np.save(os.path.join(D,'tinytp_%s.npy'%ename),a); out[ename]=a
    print('{}: n={} 익절없음 {:+.3f}%'.format(ename,len(a),a['base'].mean()*100),flush=True)
a=out['cur_30_40']; d=abs(a['base'].mean()*100-(-4.798))
print()
print('재현검증: {:+.3f}% (목표 -4.798, 차이 {:.3f}) -> {}'.format(
    a['base'].mean()*100,d,'통과' if d<0.02 else '★실패 — 폐기'),flush=True)
