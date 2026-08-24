"""그림자 V1_notrail을 백테스트 2,399건으로 확인. 짝비교(같은 신호)."""
import pickle, numpy as np, datetime as dt, engine as E
rng=np.random.default_rng(20260824)
d=pickle.load(open('events.pkl','rb'))
v0=[];v1=[];sym=[];hold=[];day=[];kind0=[]
for r in d['real']:
    se=r['opt']
    a=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
    sv=se.trail; se.trail=None
    b=E.evaluate(se,None,0.0,40.0,40.0,funding_fn=E.funding)
    se.trail=sv
    v0.append(a['ret']*100); v1.append(b['ret']*100); kind0.append(a['kind'])
    sym.append(r['sym']); hold.append(r['hold'])
    day.append(dt.datetime.utcfromtimestamp(r['t0']/1000).strftime('%Y-%m-%d'))
v0=np.array(v0);v1=np.array(v1);sym=np.array(sym);hold=np.array(hold,bool)
day=np.array(day);kind0=np.array(kind0); df=v1-v0
print('=== 백테스트 2,399건: 트레일링 제거(V1) vs 현행(V0), 증거금 기준 ===')
print('  V0 {:+.2f}%   V1 {:+.2f}%   짝차이 {:+.2f}%p'.format(v0.mean(),v1.mean(),df.mean()))
nz=df[df!=0]; print('  차이 있는 건 {}건  V1승 {}  V0승 {}'.format(len(nz),(nz>0).sum(),(nz<0).sum()))
def boot(x,s,B=4000):
    u=np.unique(s); idx={k:np.nonzero(s==k)[0] for k in u}; o=np.empty(B)
    for i in range(B):
        p=rng.integers(0,len(u),len(u))
        o[i]=x[np.concatenate([idx[u[k]] for k in p])].mean()
    return o
b=boot(df,sym); lo,hi=np.percentile(b,[2.5,97.5])
print()
print('[사전 확정 4조건]')
c1=df.mean()>0;                       print('  1. 짝차이 > 0            : {:+.2f}%p  {}'.format(df.mean(),'충족' if c1 else '미충족'))
c2=(lo>0)or(hi<0);                    print('  2. 부트스트랩 95%CI      : [{:+.2f}, {:+.2f}]  {}'.format(lo,hi,'0 제외(충족)' if c2 else '0 포함(미충족)'))
dh=df[hold].mean(); c3=np.sign(dh)==np.sign(df.mean())
print('  3. 홀드아웃 부호 일치    : {:+.2f}%p (n={})  {}'.format(dh,hold.sum(),'충족' if c3 else '미충족'))
mr=day!='2025-10-11'; dx=df[mr].mean(); c4=np.sign(dx)==np.sign(df.mean())
print('  4. 10-11 제외 부호 일치  : {:+.2f}%p  {}'.format(dx,'충족' if c4 else '미충족'))
print()
print('  ==> {} ({}/4)'.format('통과' if all([c1,c2,c3,c4]) else '미통과', sum([c1,c2,c3,c4])))
print()
m=kind0=='trail'
print('[그림자와 같은 분해] V0가 트레일링으로 끝난 건만')
print('  {}건 ({:.1f}%)  짝차이 {:+.2f}%p  V1승 {} / V0승 {}'.format(m.sum(),m.mean()*100,df[m].mean(),(df[m]>0).sum(),(df[m]<0).sum()))
print('  나머지 {}건 짝차이 {:+.2f}%p'.format((~m).sum(),df[~m].mean()))
