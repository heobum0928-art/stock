"""prereg #41 PREREG_HIGHRISK_REGIME.md"""
import json,numpy as np,collections,datetime as dt
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
E=json.load(open(S+'ext_regime.json'))
def run(ev,L,q,fee):
    by=collections.defaultdict(list)
    for (p,d,s,sd,rs,rc,adv,adv_stop,reg) in ev:
        if sd!='S' or reg>0: continue          # 하락 국면(≤0)만
        r=-1.0 if adv_stop*L>=(1-0.005*L) else rs*L-fee*L
        by[d].append(max(r,-1.0))
    eq=1.0;peak=1.0;mdd=0
    for d in sorted(by):
        eq*=1+q*float(np.mean(by[d]));eq=max(eq,1e-6);peak=max(peak,eq);mdd=min(mdd,eq/peak-1)
    return eq,mdd,sum(len(v) for v in by.values())
P={'C 2021~22':[e for e in E if e[0]=='C'],'B 2023~25':[e for e in E if e[0]=='B'],'A 2025~26':[e for e in E if e[0]=='A']}
for fee,tag in ((0.0012,'비용 0.12%'),(0.0024,'슬리피지 2배 0.24%')):
    print(f'\n=== {tag} — 자본 배수(MDD) C / B / A  [하락 국면 숏만]')
    res={}
    for L in (2,3,4,5):
        for q in (0.05,0.10,0.20):
            res[(L,q)]={k:run(v,L,q,fee) for k,v in P.items()}
            v=res[(L,q)]
            print(f'L={L} q={q*100:>3.0f}% | '+' | '.join(f'{k.split()[0]} {e:6.2f}배({m*100:4.0f}%)' for k,(e,m,n) in v.items())+(' ← 세 기간 모두>1' if all(e>1 for e,_,_ in v.values()) else ''))
    ok={k:v for k,v in res.items() if all(e>1 for e,_,_ in v.values())}
    if ok:
        best=max(ok,key=lambda k:min(e for e,_,_ in ok[k].values()))
        print(f'세 기간 모두>1.0인 칸 {len(ok)}/12. maximin: L={best[0]} q={best[1]*100:.0f}% → 기간별 {[round(e,2) for e,_,_ in ok[best].values()]}, 최대낙폭 {min(m for _,m,_ in ok[best].values())*100:.0f}%')
    else: print('세 기간 모두 >1.0인 칸 없음')
    if fee==0.0012:
        print('기간별 건수:',{k:v[0][2] for k,v in [(k,run(vv,2,0.05,0.0012)[0:3]) for k,vv in P.items()] for _ in [0]} if False else {k:run(vv,2,0.05,0.0012)[2] for k,vv in P.items()})
        print('판정:','성립' if ok else '기각')
