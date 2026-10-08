"""prereg #48 PREREG_BARBELL.md"""
import json,datetime as dt,numpy as np,collections
src=open('scripts/trend200_eth_sol.py',encoding='utf-8').read();exec(src[:src.index('def st_')])
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
D,r,h=run('BTCUSDT');D=D[199:]
A={d:x for d,x in zip(D,r)}
def bser(cost):
    ev=[];
    for p,f,lo,hi in (('C','ext_C.json',dt.date(2021,3,1),dt.date(2022,12,31)),('B','ext_B.json',dt.date(2023,2,1),dt.date(2024,12,31)),('A','ext_A.json',dt.date(2025,1,1),dt.date(2026,9,30))):
        for (d,s,sd,rs,rc,adv,adv_stop) in json.load(open(S+f)):
            dd=dt.date.fromisoformat(d)
            if sd=='S' and lo<=dd<=hi: ev.append((dd,rs,adv_stop))
    by=collections.defaultdict(list);L=3
    for dd,rs,adv_stop in ev:
        x=-1.0 if adv_stop*L>=(1-0.005*L) else rs*L-cost*L
        by[dd].append(max(x,-1.0))
    return {d:0.10*float(np.mean(v)) for d,v in by.items()}
def stats(x):
    e=np.cumprod(1+np.array(x));yrs=len(x)/365;mdd=(e/np.maximum.accumulate(e)-1).min();c=e[-1]**(1/yrs)-1
    return e[-1],c,mdd,(c/abs(mdd) if mdd else 0)
for cost,tag in ((0.0012,'비용 0.12%'),(0.0024,'슬리피지 2배 0.24%')):
    B=bser(cost)
    days=sorted(d for d in A if (dt.date(2021,3,1)<=d<=dt.date(2022,12,31)) or (dt.date(2023,2,1)<=d<=dt.date(2026,9,30)))
    a=np.array([A[d] for d in days]);b=np.array([B.get(d,0.0) for d in days]);c=0.5*a+0.5*b
    print(f'\n=== {tag} — {len(days)}일, B 신호일 {sum(1 for d in days if d in B)}일')
    for nm,x in (('A BTC 200일선',a),('B 알트 NR7 숏(3배·10%)',b),('조합 50/50',c)):
        e,cg,m,cal=stats(x);print(f'{nm}: 누적 {e:.2f}배 연복리 {cg:+.0%} MDD {m:.0%} 칼마 {cal:.2f}')
    print(f'일수익 상관(A,B): {np.corrcoef(a,b)[0,1]:+.3f}')
    ys=sorted(set(d.year for d in days))
    for y in ys:
        k=np.array([d.year==y for d in days]);print(f'  {y}: A {np.prod(1+a[k])-1:+.0%} B {np.prod(1+b[k])-1:+.0%} 조합 {np.prod(1+c[k])-1:+.0%}')
    if cost==0.0012:
        ca,cb,cc=stats(a)[3],stats(b)[3],stats(c)[3];print('판정:','성립' if cc>ca and cc>cb else '기각',f'(칼마 조합 {cc:.2f} vs A {ca:.2f}, B {cb:.2f})')
