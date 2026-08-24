"""모멘텀 스윕 상위 후보 독립 재현 검증"""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import swlib as L, numpy as np, pandas as pd, datetime as dt
K=288; THR=[30.,40.,50.]
acc={t:{'r':[],'t':[],'s':[]} for t in THR}
base={'r':[],'t':[]}
for si,sym in enumerate(L.symbols('disc')):
    d=L.load(sym); c=d['c']; l=d['l']; t=d['t']
    if len(c)<K+600: continue
    m,LO,SH=L.fwd_returns(d,sym)
    mn=pd.Series(l.astype(float)).rolling(K,min_periods=K).min().to_numpy()
    du=(c/mn-1.0)*100.0
    cont=np.zeros(len(t),bool); cont[K-1:]=(t[K-1:]-t[:len(t)-K+1])==(K-1)*L.BAR
    r48=LO['48h']
    ok=m&cont&np.isfinite(du)&np.isfinite(r48)
    # 에이전트와 동일: UTC 정시 격자(12봉마다 1개)로 중복표본 축소
    grid=(t%3600000)==0
    ok=ok&grid
    base['r'].append(r48[m&np.isfinite(r48)&grid]); base['t'].append(t[m&np.isfinite(r48)&grid])
    for th in THR:
        sel=ok&(du>=th)
        if sel.any():
            acc[th]['r'].append(r48[sel]); acc[th]['t'].append(t[sel]); acc[th]['s'].append(np.full(sel.sum(),si))
    if (si+1)%150==0: print('  {}종목'.format(si+1),flush=True)
br=np.concatenate(base['r']); bt=np.concatenate(base['t'])
bmo=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in bt])
print()
print('기준선(무조건 롱 48h): 전체 {:+.3f}%  (n={:,})'.format(br.mean(),len(br)))
print('  2025-10 제외        : {:+.3f}%'.format(br[bmo!='2025-10'].mean()))
print()
print('{:28s} {:>8} {:>6} {:>8} {:>8} {:>7} {:>10} {:>9}'.format('조건','n','종목','평균%','중앙%','승률','10월제외','월일치'))
for th in THR:
    if not acc[th]['r']: continue
    r=np.concatenate(acc[th]['r']); tt=np.concatenate(acc[th]['t']); ss=np.concatenate(acc[th]['s'])
    mo=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in tt])
    ex=r[mo!='2025-10']
    um=np.unique(mo); same=sum(1 for x in um if np.sign(r[mo==x].mean())==np.sign(r.mean()))
    print('288봉 저점대비 >= +{:.0f}%{:9s} {:>8,} {:>6} {:>8.3f} {:>8.3f} {:>6.1f}% {:>9.3f}% {:>6}/{:<2}'.format(
        th,'',len(r),len(np.unique(ss)),r.mean(),np.median(r),(r>0).mean()*100,ex.mean(),same,len(um)))
    print('{:28s} {:>8} {:>6} {:>8} {:>8} {:>7} {:>10} {:>9}'.format(
        '  10월 제외 기준선 대비','','','','','','{:+.3f}%p'.format(ex.mean()-br[bmo!='2025-10'].mean()),''))
