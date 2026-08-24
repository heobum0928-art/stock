"""후보4(DU_48>+50% -> 24h 숏)를 바이낸스 선물에서 재현. docs/PREREG_DU50_BINANCE.md"""
import os,sys,glob,hashlib,numpy as np,pandas as pd,datetime as dt
D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq'); FD=os.path.join(D,'fund')
BAR=300000; HOLD=288; COST=0.0006; WIN_S=1754006400000; WIN_E=1785523200000
COOL=12*3600*1000
def hold_of(s): return int(hashlib.md5(s.encode()).hexdigest(),16)%4==0
def cumfund(sym,t0,tx):
    p=os.path.join(FD,sym+'.npz')
    if not os.path.exists(p): return 0.0
    z=np.load(p); ft=z[z.files[0]]; fr=z[z.files[1]]
    cs=np.concatenate(([0.0],np.cumsum(fr)))
    return float(cs[np.searchsorted(ft,tx,'right')]-cs[np.searchsorted(ft,t0,'right')])

def scan(sym, rand_pts=None):
    z=np.load(os.path.join(PQ,sym+'.npz'))
    t,o,h,l,c=z['t'],z['o'],z['h'],z['l'],z['c']
    n=len(t)
    if n<HOLD+60: return []
    mn=pd.Series(l.astype(float)).rolling(48,min_periods=48).min().to_numpy()
    du=(c/mn-1.0)*100.0
    cont48=np.zeros(n,bool); cont48[47:]=(t[47:]-t[:n-47])==47*BAR
    if rand_pts is None:
        idx=np.flatnonzero(cont48 & np.isfinite(du) & (du>50.0) & (t>=WIN_S) & (t<WIN_E))
    else:
        idx=np.array([i for i in rand_pts if 0<=i<n],dtype=np.int64)
    out=[]; last=-1e18
    for i in idx:
        if i+1+HOLD>=n: continue
        if t[i]-last < COOL: continue          # 12h 종목 쿨다운
        if t[i+1+HOLD]-t[i+1] != HOLD*BAR: continue   # 연속성
        last=t[i]
        P0=float(o[i+1]); PX=float(c[i+1+HOLD])
        if P0<=0: continue
        price=-(PX/P0-1.0)*100.0               # 숏
        fee=-COST*2*100.0
        fund=cumfund(sym,int(t[i+1]),int(t[i+1+HOLD]))*100.0   # 숏은 양수 펀딩 수취
        out.append((sym,int(t[i]),price,fund,fee,price+fund+fee,hold_of(sym)))
    return out

syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,'*.npz')))
real=[]
for k,s in enumerate(syms):
    try: real+=scan(s)
    except Exception as e: pass
    if (k+1)%200==0: print('  {}/{}'.format(k+1,len(syms)),flush=True)
# 무작위 대조군: base_rand 의 (sym,t0) 지점에 동일 규칙
z=np.load('base_rand.npz',allow_pickle=True)
rs,rt=z['sym'],z['t0'].astype(np.int64)
from collections import defaultdict
by=defaultdict(list)
for s,tt in zip(rs,rt): by[str(s)].append(tt)
rand=[]
for s,tts in by.items():
    try:
        zz=np.load(os.path.join(PQ,s+'.npz')); tarr=zz['t']
        pts=[int(np.searchsorted(tarr,x)) for x in tts]
        pts=[i for i in pts if i<len(tarr) and tarr[i]==tts[pts.index(i)] if True]
        rand+=scan(s, rand_pts=[int(np.searchsorted(tarr,x)) for x in tts])
    except Exception: pass
np.save('du50_real.npy',np.array(real,dtype=object),allow_pickle=True)
np.save('du50_rand.npy',np.array(rand,dtype=object),allow_pickle=True)
print('신호 {}건 / 무작위 {}건'.format(len(real),len(rand)))
