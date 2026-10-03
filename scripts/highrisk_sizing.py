"""prereg #39 PREREG_HIGHRISK_SIZING.md"""
import json,numpy as np,collections
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
P={'C 2021~22':json.load(open(S+'ext_C.json')),'B 2023~25':json.load(open(S+'ext_B.json')),'A 2025~26':json.load(open(S+'ext_A.json'))}
def run(ev,L,q,fee=0.0012):
    by=collections.defaultdict(list)
    for (d,s,sd,rs,rc,adv,adv_stop) in ev:
        if sd!='S': continue
        r=-1.0 if adv_stop*L>=(1-0.005*L) else rs*L-fee*L
        by[d].append(max(r,-1.0))
    eq=1.0;peak=1.0;mdd=0
    for d in sorted(by):
        n=len(by[d]);eq*=1+q*float(np.sum(by[d]))/n*min(n,1) if False else 1+q*float(np.mean(by[d]));eq=max(eq,1e-6);peak=max(peak,eq);mdd=min(mdd,eq/peak-1)
    return eq,mdd
def table(fee):
    res={}
    for L in (2,3,4,5):
        for q in (0.05,0.10,0.20):
            res[(L,q)]={k:run(v,L,q,fee) for k,v in P.items()}
    return res
for fee,tag in ((0.0012,'비용 0.12%'),(0.0024,'슬리피지 2배 0.24%')):
    res=table(fee);print(f'\n=== {tag} — 자본 배수(MDD) 기간 C / B / A')
    for (L,q),v in res.items():
        print(f'L={L} q={q*100:>3.0f}% | '+' | '.join(f'{k.split()[0]} {e:6.2f}배({m*100:4.0f}%)' for k,(e,m) in v.items())+(' ← 세 기간 모두>1' if all(e>1 for e,_ in v.values()) else ''))
    ok={k:v for k,v in res.items() if all(e>1 for e,_ in v.values())}
    if ok:
        best=max(ok,key=lambda k:min(e for e,_ in ok[k].values()));print(f'세 기간 모두>1.0인 칸 {len(ok)}개. maximin: L={best[0]} q={best[1]*100:.0f}% → 최소 {min(e for e,_ in ok[best].values()):.2f}배, 최대낙폭 {min(m for _,m in ok[best].values())*100:.0f}%')
    else: print('세 기간 모두 >1.0인 칸 없음')
    if fee==0.0012: print('판정:','성립' if ok else '기각')
