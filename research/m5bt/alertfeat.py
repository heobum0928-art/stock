"""PREREG_ALERT_FEATURES.md 실행 — -20%(증거금) 도달 시점의 7개 특징."""
import os,glob
import numpy as np
import engine as E, signals as S, build as BU
D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq'); HOLD=576
LIQ=(1-2.0*E.MMR)/(2.0*(1+E.MMR))*100
TOUCH=10.0                                    # 명목 10% = 증거금 20%
LEVELS=sorted(set([TOUCH,8.,12.,16.,20.,25.,30.,40.]))+[LIQ]
E.LEVELS=LEVELS; E.IDX={v:i for i,v in enumerate(LEVELS)}; E.LIQ_IDX=len(LEVELS)-1
bt_t,_,_,_,bt_c,_=S.load('BTCUSDT')
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))
rows=[]; allret=[]
for n_,s in enumerate(syms):
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
        r=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
        allret.append(r['ret'])
        tch=f[E.IDX[TOUCH]]
        if tch is None or tch[1]>r['exit_bar']: continue
        b=tch[1]                                     # 도달 봉 인덱스(진입 다음봉 기준)
        qs=qv[sl]
        f1=(b+1)*5.0                                 # 1 도달 속도(분)
        f2=float(ret7)                               # 2 진입 급등폭
        f3=float(v24)                                # 3 유동성
        pre=qv[max(0,i-288):i+1]
        hravg=pre.sum()/24.0 if pre.sum()>0 else np.nan
        last1h=qs[max(0,b-11):b+1].sum()
        f4=last1h/hravg if hravg and hravg>0 else np.nan   # 4 거래량 급증
        k0=np.searchsorted(bt_t,int(t[i]),'right')-1; k1=np.searchsorted(bt_t,int(bt[b]),'right')-1
        f5=(bt_c[k1]/bt_c[k0]-1)*100 if 0<=k0<len(bt_c) and 0<=k1<len(bt_c) else np.nan  # 5 BTC
        f6=float(cf[b])*100                          # 6 누적 펀딩률(%)
        f7=(1-float(ll[:b+1].min())/P0)*100*2        # 7 도달 전 최유리(증거금%)
        rows.append((s,int(ts),bool(BU.holdout(s)),r['ret']*100,f1,f2,f3,f4,f5,f6,f7))
    if (n_+1)%200==0: print('  {}/{} 도달 {}'.format(n_+1,len(syms),len(rows)),flush=True)
print('재현검증: 전체 평균 {:+.3f}%  (목표 -4.798)'.format(np.mean(allret)*100),flush=True)
dt=[('sym','U15'),('t0','i8'),('hold','?'),('ret','f8'),('speed','f8'),('pump','f8'),
    ('qv','f8'),('volsurge','f8'),('btc','f8'),('fund','f8'),('mfe_pre','f8')]
a=np.array(rows,dtype=dt); np.save(os.path.join(D,'alertfeat.npy'),a)
print('-20% 도달 {}건 저장'.format(len(a)),flush=True)
