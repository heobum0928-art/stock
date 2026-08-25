"""진입 후 시점별 승률·손익 — '그 시각에 시장가로 닫았다면'. 검증된 엔진 사용."""
import os,glob
import numpy as np
import engine as E, signals as S, build as BU
D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq'); HOLD=576
LEV=2.0; RT=0.0012   # 왕복 명목 0.12%
LIQ=(1-2.0*E.MMR)/(2.0*(1+E.MMR))*100
LEVELS=[8.,12.,16.,20.,25.,30.,40.,LIQ]
E.LEVELS=LEVELS; E.IDX={v:i for i,v in enumerate(LEVELS)}; E.LIQ_IDX=len(LEVELS)-1
TS=[('30분',6),('1시간',12),('2시간',24),('4시간',48),('8시간',96),('24시간',288),('48시간',576)]
acc={lab:[] for lab,_ in TS}; chk=[]
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
        chk.append(E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)['ret'])
        stp=f[E.IDX[40.0]]                       # 손절(명목 +40%) 도달 봉
        sb=stp[1] if stp is not None else 10**9
        for lab,H in TS:
            b=min(H,len(cc))-1
            if b<0: continue
            if sb<=b:                            # 그 전에 손절됐다
                acc[lab].append(-80.0); continue
            r=(1-float(cc[b])/P0-RT)*100*LEV + float(cf[b])*100*LEV
            acc[lab].append(max(r,-100.0))
    if (n_+1)%200==0: print('  {}/805'.format(n_+1),flush=True)
print('재현검증(현행 규칙 최종): {:+.3f}%  목표 -4.798'.format(np.mean(chk)*100),flush=True)
print()
print('=== 진입 후 그 시각에 시장가로 닫았다면 (증거금 기준, 펀딩·수수료 포함) ===')
print('{:>8} {:>7} {:>9} {:>10} {:>10} {:>10}'.format('경과','건수','승률','평균','중앙값','손절도달'))
print('-'*60)
for lab,H in TS:
    a=np.array(acc[lab])
    print('{:>8} {:>7} {:>8.1f}% {:>+9.2f}% {:>+9.2f}% {:>9.1f}%'.format(
        lab,len(a),100*(a>0).mean(),a.mean(),np.median(a),100*(a<=-79.9).mean()))
