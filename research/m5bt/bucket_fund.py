"""급등폭 구간별 성적 — 펀딩 실측 포함, 현행 출구규칙(손절40%+트레일링) 적용.
서술적 측정. 결과 보고 채택하지 않는다(CLAUDE.md 5항)."""
import os,glob,numpy as np
PQ='pq'; FD='fund'; BAR=300000; HOLD=576; LEV=2.0; RT=0.0012
LB=84; VOLWIN=288; MINQV=3e6; NEW=30*24*3600*1000; COOL=12*3600*1000
WIN_S=1754006400000; WIN_E=1785523200000
STOP=40.0; TRAIL_ARM=15.0; TRAIL_GB=10.0     # 현행 봇 규칙(증거금 기준 %)
BUCKETS=[(15,20),(20,30),(30,40),(40,60),(60,1e9)]
_fc={}
def cumf(sym,t0,tx):
    if sym not in _fc:
        p=os.path.join(FD,sym+'.npz')
        if not os.path.exists(p): _fc[sym]=None
        else:
            z=np.load(p); ft=z[z.files[0]]; fr=z[z.files[1]]
            _fc[sym]=(ft,np.concatenate(([0.0],np.cumsum(fr))))
    v=_fc[sym]
    if v is None: return 0.0
    ft,cs=v
    return float(cs[np.searchsorted(ft,tx,'right')]-cs[np.searchsorted(ft,t0,'right')])
acc={b:{'px':[],'fd':[],'net':[],'liq':0} for b in BUCKETS}
for p in sorted(glob.glob(os.path.join(PQ,'*.npz'))):
    s=os.path.basename(p)[:-4]; z=np.load(p)
    t,o,h,l,c,qv=z['t'],z['o'],z['h'],z['l'],z['c'],z['qv']; n=len(t)
    if n<LB+VOLWIN+700: continue
    ok=np.zeros(n,bool); ok[LB:]=(t[LB:]-t[:-LB])==LB*BAR
    ret=np.full(n,np.nan); ret[LB:]=(c[LB:]/c[:-LB]-1)*100
    cs=np.concatenate(([0.],np.cumsum(qv))); v24=np.full(n,np.nan); v24[VOLWIN-1:]=cs[VOLWIN:]-cs[:n-VOLWIN+1]
    base=ok&(v24>=MINQV)&((t-t[0])>=NEW)&(t>=WIN_S)&(t<WIN_E)
    for b in BUCKETS:
        idx=np.flatnonzero(base&(ret>=b[0])&(ret<b[1])); last=-1e18
        for i in idx:
            if t[i]-last<COOL: continue
            j=min(i+1+HOLD,n)
            if j-(i+1)<12: continue
            last=t[i]; P0=float(c[i])
            hh,ll,cc=h[i+1:j],l[i+1:j],c[i+1:j]
            stp=P0*(1+STOP/100/LEV)          # 증거금 40% = 가격 20%
            ex=None; xi=len(cc)-1; peak=0.0; armed=False
            for k in range(len(cc)):
                if hh[k]>=stp: ex=stp; xi=k; break          # 손절 먼저(보수)
                pk=(1-ll[k]/P0)*100*LEV
                if pk>peak: peak=pk
                if peak>=TRAIL_ARM: armed=True
                cur=(1-cc[k]/P0)*100*LEV
                if armed and cur<=peak-TRAIL_GB:
                    ex=float(cc[k]); xi=k; break
            if ex is None: ex=float(cc[-1])
            px=(1-ex/P0-RT)*100*LEV
            fd=-cumf(s,float(t[i+1]),float(t[i+1+xi]))*100*LEV   # 숏은 양수펀딩 수취
            acc[b]['px'].append(px); acc[b]['fd'].append(fd); acc[b]['net'].append(px+fd)
print('현행 출구규칙(손절 증거금40% + 트레일링 15/10) · 펀딩 실측 · 증거금 기준 %')
print()
print('{:<10} {:>6} {:>10} {:>9} {:>10} {:>8}'.format('급등폭','건수','가격','펀딩','순손익','승률'))
print('-'*58)
for b in BUCKETS:
    a=acc[b]
    if not a['net']: continue
    lab='{}~{}%'.format(b[0],'' if b[1]>1e8 else int(b[1]))
    net=np.array(a['net'])
    se=net.std(ddof=1)/np.sqrt(len(net))
    star='  현행' if b==(30,40) else ''
    print('{:<10} {:>6} {:>+9.2f}% {:>+8.2f}% {:>+9.2f}% {:>7.1f}%   (SE {:.2f}){}'.format(
        lab,len(net),np.mean(a['px']),np.mean(a['fd']),net.mean(),100*(net>0).mean(),se,star))
