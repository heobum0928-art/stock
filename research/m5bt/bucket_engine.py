"""PREREG_PUMP_LOWER.md 실행 — 검증된 엔진 그대로 사용. 재구현 금지."""
import os,json,glob,pickle,sys
import numpy as np
import engine as E, signals as S, build as B

D=os.path.dirname(os.path.abspath(__file__))
PQ=os.path.join(D,"pq")
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,"*.npz")))
bt_t,_,_,_,bt_c,_=S.load("BTCUSDT"); W=30*288
btcret=np.full(len(bt_c),np.nan); btcret[W:]=bt_c[W:]/bt_c[:-W]-1
def regime_at(ts):
    k=np.searchsorted(bt_t,ts,side="right")-1
    if k<0 or k>=len(btcret) or not np.isfinite(btcret[k]): return "na"
    r=btcret[k]; return "bull" if r>0.10 else ("bear" if r<-0.10 else "chop")

def run(lo,hi,tag):
    S.PUMP_LO, S.PUMP_HI = lo, hi
    out=[]
    for k,s in enumerate(syms):
        try: sg,arrs=S.sigs_for(s)
        except Exception: continue
        if not sg: continue
        t,o,h,l,c,qv=arrs
        for (i,ts,px,ret,v24) in sg:
            r=B.make(s,i,t,o,h,l,c,qv,regime_at(ts),"real")
            if r is None: continue
            a=E.evaluate(r["opt"],None,0.0,40.0,40.0,funding_fn=E.funding)
            a2=E.evaluate(r["opt"],None,0.0,40.0,40.0,funding_fn=None)
            out.append((s,int(ts),float(ret),bool(B.holdout(s)),float(a["ret"]),float(a2["ret"])))
        if (k+1)%150==0: print('  {} {}/{} 누적 {}'.format(tag,k+1,len(syms),len(out)),flush=True)
    arr=np.array(out,dtype=[('sym','U15'),('t0','i8'),('ret7h','f8'),('hold','?'),('net','f8'),('nofund','f8')])
    np.save(os.path.join(D,'bkt_%s.npy'%tag),arr)
    print('{}: n={} 평균(증거금%) {:+.3f}  [탐색 {:+.3f} / 봉인 {:+.3f}]'.format(
        tag,len(arr),arr['net'].mean()*100,
        arr['net'][~arr['hold']].mean()*100, arr['net'][arr['hold']].mean()*100),flush=True)
    return arr

print('=== 0단계: 현행 [30,40) 재현 검증 (목표 -4.80%) ===',flush=True)
v=run(30.0,40.0,'validate')
d=abs(v['net'].mean()*100 - (-4.80))
print('  확정값과 차이: {:.3f}%p -> {}'.format(d,'재현 성공' if d<0.15 else '★재현 실패 — 중단'),flush=True)
if d>=0.15: sys.exit(1)
print(flush=True)
print('=== 후보 A: [20,30) ===',flush=True); run(20.0,30.0,'A_20_30')
print('=== 후보 B: [15,20) ===',flush=True); run(15.0,20.0,'B_15_20')
print('완료',flush=True)
