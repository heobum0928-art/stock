"""사전등록 후보 5개만 평가. HALF='disc'로 먼저 재현검증 -> 'hold'는 단 한 번.
docs/PREREG_FEATURE_SWEEP.md
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, lib
import sweep_volume as SV     # build_features -> F['ats288>=1.5']
import sweep_vol as VV        # features(d), rank_of(x)

HALF = sys.argv[1] if len(sys.argv)>1 else 'disc'
assert HALF in ('disc','hold')
RT = lib.COST_SIDE*2*100.0
PAST_W = ['4h','12h']

syms = lib.symbols()
T=[];S=[];RL={k:[] for k in ('24h','48h')};PAST={w:[] for w in PAST_W}
C2=[];C4=[];C5=[]
for si,sym in enumerate(syms):
    d = lib.load(sym); t=d['t']; n=len(t)
    mask, rets = lib.fwd_returns(d, HALF)
    T.append(t); S.append(np.full(n,si,np.int32))
    for k in ('24h','48h'):
        r=rets[k].copy(); r[~mask]=np.nan; RL[k].append(r)
    for w in PAST_W:
        h=lib.HORIZONS[w]; p=np.full(n,np.nan)
        if n>h+1: p[h+1:]=rets[w][:n-h-1]
        PAST[w].append(p)
    # 후보2: ats288>=1.5  (sweep_volume 원본 함수)
    F,_liq,_n = SV.build_features(d)
    C2.append(F['ats288>=1.5'])
    # 후보4: DU_48 > +50%  (sweep_momentum 정의 그대로)
    mn = pd.Series(d['l'].astype(np.float64)).rolling(48,min_periods=48).min().to_numpy()
    C4.append((d['c']/mn-1.0)*100.0 > 50.0)
    # 후보5: rank[vr_48_288] <= 0.02  (sweep_vol 원본 함수)
    Fv,_P = VV.features(d)
    C5.append(VV.rank_of(Fv['vr_48_288']) <= 0.02)

t=np.concatenate(T); sym_id=np.concatenate(S)
retL={k:np.concatenate(RL[k]) for k in ('24h','48h')}
retS={k:lib.short_of(retL[k]) for k in ('24h','48h')}
past={w:np.concatenate(PAST[w]) for w in PAST_W}
c2=np.concatenate(C2); c4=np.concatenate(C4); c5=np.concatenate(C5)
N=len(t)
ut,tidx=np.unique(t,return_inverse=True); G=len(ut)

xrank={};xbreadth={}
for w in PAST_W:
    p=past[w]; fin=np.isfinite(p)
    cnt=np.bincount(tidx[fin],minlength=G).astype(np.float64)
    gross_up=(p+RT)>0
    upc=np.bincount(tidx[fin&gross_up],minlength=G).astype(np.float64)
    br=np.where(cnt>0,upc/np.maximum(cnt,1),np.nan)
    idx=np.flatnonzero(fin); order=np.lexsort((p[idx],tidx[idx])); sidx=idx[order]
    gt=tidx[sidx]; start=np.zeros(G,np.int64); gcnt=np.bincount(gt,minlength=G)
    start[1:]=np.cumsum(gcnt)[:-1]
    pos=np.arange(len(sidx))-start[gt]
    rk=np.full(N,np.nan); rk[sidx]=(pos+0.5)/gcnt[gt]
    xrank[w]=rk; xbreadth[w]=np.where(cnt[tidx]>0,br[tidx],np.nan)
    thin=cnt[tidx]<20
    xrank[w][thin]=np.nan; xbreadth[w][thin]=np.nan

r4,b4=xrank['4h'],xbreadth['4h']; r12,b12=xrank['12h'],xbreadth['12h']
CAND=[
 ('1. 시장폭>=70% & 횡단순위4h 상위5%','롱','48h',
   (np.isfinite(b4)&(b4>=0.70)&np.isfinite(r4)&(r4>=0.95)), retL['48h']),
 ('2. ats288>=1.5 (가격/24h중앙VWAP)','숏','48h', c2, retS['48h']),
 ('3. 시장폭<=30% & 횡단순위12h 상위2%','숏','48h',
   (np.isfinite(b12)&(b12<=0.30)&np.isfinite(r12)&(r12>=0.98)), retS['48h']),
 ('4. DU_48봉(4h저점대비) > +50%','숏','24h', c4, retS['24h']),
 ('5. rank[rv48/rv288] <= 0.02','롱','48h', c5, retL['48h']),
]
print('='*78); print('구간 = {}'.format('탐색(재현검증)' if HALF=='disc' else '★ 봉인 해제 ★')); print('='*78)
print('{:38s} {:>7} {:>8} {:>8} {:>7} {:>10}'.format('후보','n','평균%','중앙%','승률%','최대기여일제외'))
res=[]
for name,side,hz,sig,ret in CAND:
    r=lib.evaluate(np.asarray(sig,bool), ret, t, min_n=1)
    res.append((name,side,hz,r))
    if r['n']==0: print('{:38s} {:>7}'.format(name,0)); continue
    print('{:38s} {:>7} {:>8.3f} {:>8.3f} {:>7.1f} {:>10.3f}'.format(
        name[:38], r['n'], r['mean'], r['median'], r['win'], r['mean_ex_topday']))
np.save('holdout_%s_dump.npy'%HALF, np.array([1]))
import pickle; pickle.dump(res, open('holdout_%s.pkl'%HALF,'wb'))

# ---- 판정 (사전등록 §6) : hold 실행 시에만 ----
if HALF=='hold':
    import pickle
    disc=pickle.load(open('holdout_disc.pkl','rb'))
    rng=np.random.default_rng(20260824)
    day=lib.day_of(t)
    print(); print('='*78); print('사전등록 §6 판정'); print('='*78)
    # 기준선(무조건 진입) — 참고용, 판정 기준 아님
    for k in ('24h','48h'):
        fl=np.isfinite(retL[k]); print('  [참고] 기준선 {} 롱 {:+.3f}%  숏 {:+.3f}%  n={}'.format(
            k, retL[k][fl].mean(), retS[k][fl].mean(), fl.sum()))
    print()
    pv=[]; rows=[]
    for (name,side,hz,sig,ret),(dn,ds,dh,dr) in zip(CAND,disc):
        m=np.asarray(sig,bool)&np.isfinite(ret)
        n=int(m.sum())
        if n<10: rows.append((name,side,hz,n,np.nan,np.nan,np.nan,np.nan,False,False,False,False)); pv.append(1.0); continue
        r=ret[m]; dd=day[m]; ud=np.unique(dd)
        idx={u:np.flatnonzero(dd==u) for u in ud}
        B=4000; bs=np.empty(B)
        for b in range(B):
            p=rng.integers(0,len(ud),len(ud))
            bs[b]=r[np.concatenate([idx[ud[i]] for i in p])].mean()
        lo,hi=np.percentile(bs,[2.5,97.5])
        p2=2*min((bs<=0).mean(),(bs>=0).mean()); p2=max(p2,1/B)
        pv.append(p2)
        contrib={u:r[dd==u].sum() for u in ud}
        top=max(contrib,key=lambda k:abs(contrib[k])); ex=r[dd!=top].mean()
        c1=r.mean()>0; c2_=lo>0; c4_=np.sign(ex)==np.sign(r.mean()); c5_=np.sign(r.mean())==np.sign(dr['mean'])
        rows.append((name,side,hz,n,r.mean(),np.median(r),(r>0).mean()*100,ex,lo,hi,c1,c2_,c4_,c5_,dr['mean']))
    # BH-FDR q=0.10
    order=np.argsort(pv); k=len(pv); passed=set(); thr=0
    for i,oi in enumerate(order,1):
        if pv[oi] <= 0.10*i/k: thr=i
    for i,oi in enumerate(order,1):
        if i<=thr: passed.add(oi)
    print('{:32s} {:>6} {:>8} {:>8} {:>6} {:>9} {:>18}'.format('후보','n','평균%','중앙%','승률','탐색평균','95%CI'))
    for i,row in enumerate(rows):
        if len(row)<15: print('{:32s} {:>6}  표본부족'.format(row[0][:32],row[3])); continue
        name,side,hz,n,mn,md,wr,ex,lo,hi,c1,c2_,c4_,c5_,dm=row
        print('{:32s} {:>6} {:>8.3f} {:>8.3f} {:>6.1f} {:>9.3f} [{:+7.3f},{:+7.3f}]'.format(name[:32],n,mn,md,wr,dm,lo,hi))
    print()
    print('{:32s} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}'.format('후보','평균>0','CI>0','FDR','날짜','부호','판정'))
    for i,row in enumerate(rows):
        if len(row)<15: print('{:32s}  표본부족 -> 미통과'.format(row[0][:32])); continue
        name,side,hz,n,mn,md,wr,ex,lo,hi,c1,c2_,c4_,c5_,dm=row
        c3_= i in passed
        allp=c1 and c2_ and c3_ and c4_ and c5_
        f=lambda b:'O' if b else 'X'
        print('{:32s} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}'.format(name[:32],f(c1),f(c2_),f(c3_),f(c4_),f(c5_),'통과' if allp else '미통과'))
    print(); print('p값:', ['{:.4f}'.format(x) for x in pv])
