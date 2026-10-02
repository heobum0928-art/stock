"""prereg #35 PREREG_EXTREME_FLEET.md — 16변형 × 2기간 (탐색)"""
import json,numpy as np,collections
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
FEE=0.0012;Q=0.10
def variant(ev,side,L,stop):
    by=collections.defaultdict(list);liq=0;n=0;wins=[];losses=[]
    for (d,s,sd,rs,rc,adv,adv_stop) in ev:
        if sd!=side: continue
        gross=rs if stop else rc;ad=adv_stop if stop else adv
        r=-1.0 if ad*L>=(1-0.005*L) else gross*L-FEE*L   # 유지증거금 근사: 불리 극단이 1/L-0.5% 이상이면 전액 손실
        if r<=-1.0: r=-1.0;liq+=1
        by[d].append(r);n+=1;(wins if r>0 else losses).append(r)
    if not n: return None
    eq=1.0;peak=1.0;mdd=0
    for d in sorted(by):
        eq*=1+Q*float(np.mean(by[d]));eq=max(eq,0);peak=max(peak,eq);mdd=min(mdd,eq/peak-1)
    allr=[r for v in by.values() for r in v]
    return dict(n=n,mean=np.mean(allr),liq=liq/n,win=len(wins)/n,eq=eq,mdd=mdd)
A=json.load(open(S+'ext_A.json'));B=json.load(open(S+'ext_B.json'))
print('방향 레버 손절 | 기간A(2025~26): 건 평균(증거금) 청산% 복리 MDD | 기간B(2023~25): 건 평균 청산% 복리 MDD')
res=[]
for side in ('S','L'):
    for L in (1,5,10,20):
        for stop in (True,False):
            a=variant(A,side,L,stop);b=variant(B,side,L,stop)
            tag=f'{"숏" if side=="S" else "롱"} {L:>2}배 {"손절" if stop else "무손절"}'
            print(f'{tag} | A {a["n"]:4d} {a["mean"]*100:+7.1f}% {a["liq"]*100:4.0f}% {a["eq"]:6.2f}배 {a["mdd"]*100:4.0f}% | B {b["n"]:4d} {b["mean"]*100:+7.1f}% {b["liq"]*100:4.0f}% {b["eq"]:6.2f}배 {b["mdd"]*100:4.0f}%')
            res.append((tag,a,b))
ok=[(t,a,b) for t,a,b in res if a['eq']>1 and b['eq']>1]
print('\n두 기간 모두 복리>1.0배:',[(t,round(a['eq'],2),round(b['eq'],2)) for t,a,b in ok] or '없음')
bestA=max(res,key=lambda x:x[1]['eq']);bestB=max(res,key=lambda x:x[2]['eq'])
print('A 최고(사후, 참고):',bestA[0],round(bestA[1]['eq'],2),'| B 최고:',bestB[0],round(bestB[2]['eq'],2))
