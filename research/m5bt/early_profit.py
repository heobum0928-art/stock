"""진입 후 '초반에 플러스'가 얼마나 자주 오는가 — 급등폭 구간별.
서술적 측정이다. 여기서 좋아 보이는 구간을 전략으로 채택하지 않는다(CLAUDE.md 5항).
숏 2배. 보고는 증거금 기준(=가격변동×2). 왕복비용 0.12%(명목)=0.24%(증거금) 차감."""
import os,glob,numpy as np
PQ='pq'; BAR=300000; HOLD=576; LEV=2.0; RT=0.0012   # 왕복 명목
LB=84; VOLWIN=288; MINQV=3e6; NEW=30*24*3600*1000; COOL=12*3600*1000
WIN_S=1754006400000; WIN_E=1785523200000
BUCKETS=[(15,20),(20,30),(30,40),(40,60),(60,1e9)]   # (30,40)이 현행
HOR={'1h':12,'2h':24,'4h':48,'8h':96,'24h':288,'48h':576}
acc={b:{'n':0,'peak':{k:[] for k in HOR},'fin':[]} for b in BUCKETS}
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))
for s in syms:
    z=np.load(os.path.join(PQ,s+'.npz'))
    t,o,h,l,c,qv=z['t'],z['o'],z['h'],z['l'],z['c'],z['qv']
    n=len(t)
    if n<LB+VOLWIN+700: continue
    ok=np.zeros(n,bool); ok[LB:]=(t[LB:]-t[:-LB])==LB*BAR
    ret=np.full(n,np.nan); ret[LB:]=(c[LB:]/c[:-LB]-1)*100
    cs=np.concatenate(([0.],np.cumsum(qv))); v24=np.full(n,np.nan); v24[VOLWIN-1:]=cs[VOLWIN:]-cs[:n-VOLWIN+1]
    base=ok&(v24>=MINQV)&((t-t[0])>=NEW)&(t>=WIN_S)&(t<WIN_E)
    for b in BUCKETS:
        sel=base&(ret>=b[0])&(ret<b[1])
        idx=np.flatnonzero(sel); last=-1e18
        for i in idx:
            if t[i]-last<COOL: continue
            j=min(i+1+HOLD,n)
            if j-(i+1)<12: continue
            last=t[i]; P0=float(c[i])
            ll=l[i+1:j]; cc=c[i+1:j]
            # 숏: 가격이 내려가면 이익. 최유리 = 구간 최저가
            acc[b]['n']+=1
            for k,H in HOR.items():
                m=min(H,len(ll))
                pk=(1-float(ll[:m].min())/P0-RT)*100*LEV   # 증거금 기준 %
                acc[b]['peak'][k].append(pk)
            acc[b]['fin'].append((1-float(cc[-1])/P0-RT)*100*LEV)
print('숏 2배 · 증거금 기준 % · 왕복비용 차감 · 손절/트레일링 없음 · 펀딩 미반영')
print()
print('{:<10} {:>6} | {}'.format('급등폭','건수',' '.join('{:>7}'.format(k) for k in HOR)))
print('-'*72)
for b in BUCKETS:
    a=acc[b]
    if a['n']==0: continue
    lab='{}~{}%'.format(b[0],'' if b[1]>1e8 else int(b[1]))
    row=' '.join('{:>6.1f}%'.format(100*np.mean(np.array(a['peak'][k])>0)) for k in HOR)
    print('{:<10} {:>6} | {}   <- 한번이라도 +였던 비율'.format(lab,a['n'],row))
print()
print('{:<10} {:>6} | {:>9} {:>9} {:>9}'.format('급등폭','건수','최유리2h','최유리4h','48h최종평균'))
print('-'*52)
for b in BUCKETS:
    a=acc[b]
    if a['n']==0: continue
    lab='{}~{}%'.format(b[0],'' if b[1]>1e8 else int(b[1]))
    print('{:<10} {:>6} | {:>8.2f}% {:>8.2f}% {:>+9.2f}%'.format(
        lab,a['n'],np.median(a['peak']['2h']),np.median(a['peak']['4h']),np.mean(a['fin'])))
