import numpy as np, json, os, pickle
BAR=300_000; LOOKBACK=84; STOP=0.40; HOLD_BARS=48*12
TRAIL_TRIG=15.0; TRAIL_GB=10.0; LEV=2.0; MIN_QV=3e6
FEE=0.0008; SLIP=0.0004; STOPX=0.0005; MMR=0.05
KEEP=json.load(open('keep_syms.json'))
D=pickle.load(open('signals.pkl','rb')); SIGS=D['sigs']
T0=D['T0']; T1=D['T1']; N=D['N']; GRID_TS=T0+BAR*np.arange(N)

def load(sym):
    z=np.load(f'data/{sym}.npz'); return (z['ts'].astype(np.int64),z['o'].astype(np.float64),
        z['h'].astype(np.float64),z['l'].astype(np.float64),z['c'].astype(np.float64),z['qv'].astype(np.float64))
def regrid(ts,o,h,l,c,qv):
    idx=((ts-T0)//BAR).astype(np.int64); m=(idx>=0)&(idx<N)
    O=np.full(N,np.nan);H=np.full(N,np.nan);L=np.full(N,np.nan);C=np.full(N,np.nan);QV=np.zeros(N)
    O[idx[m]]=o[m];H[idx[m]]=h[m];L[idx[m]]=l[m];C[idx[m]]=c[m];QV[idx[m]]=qv[m]
    return O,H,L,C,QV
from numpy.lib.stride_tricks import sliding_window_view
zb=np.load('data/BTCUSDT.npz'); bO,bH,bL,bC,_=regrid(*load('BTCUSDT'))
hh=np.full(N,np.nan);hh[287:]=np.nanmax(sliding_window_view(bH,288),axis=1)
ll=np.full(N,np.nan);ll[287:]=np.nanmin(sliding_window_view(bL,288),axis=1)
op=np.roll(bO,287);op[:287]=np.nan
BTCVOL=(hh-ll)/op*100; REGIME_OK=~(BTCVOL>3.26)
FUND={}
for s in KEEP:
    p=f'fund/{s}.npz'
    if os.path.exists(p): z=np.load(p); FUND[s]=(z['ts'],z['r'])
def fsum(sym,a,b):
    z=FUND.get(sym)
    if z is None: return 0.0
    ft,fr=z; return float(fr[(ft>a)&(ft<=b)].sum())

def sim(O,H,L,C,ei,P0,realistic=True):
    stop_px=P0*1.40; liq_px=1.5*P0/(1+MMR); mfe=P0
    last=min(N-1,ei+HOLD_BARS)
    for i in range(ei,last+1):
        h=H[i]
        if np.isnan(h): continue
        trail_lvl=mfe+0.10*P0 if (1-mfe/P0)*100>=TRAIL_TRIG else np.inf
        if h>=stop_px:
            fill=max(stop_px,O[i]) if realistic else stop_px
            # if realistic fill is beyond liq line -> liquidation
            if realistic and fill>=liq_px: return None,i,'liq'
            return fill,i,'stop'
        if h>=trail_lvl:
            return (max(trail_lvl,O[i]) if not np.isnan(O[i]) else trail_lvl),i,'trail'
        if L[i]<mfe: mfe=L[i]
    j=last
    while j>ei and np.isnan(O[j]): j-=1
    return (O[j] if not np.isnan(O[j]) else C[ei]),j,('expiry' if last==ei+HOLD_BARS else 'dataend')

def pnl(sym,P0,px,ei,xi,kind):
    if kind=='liq': return -1.0
    r=(P0-px)/P0; cost=FEE+SLIP+(STOPX if kind in('stop','trail') else 0)
    return LEV*(r-cost)+LEV*fsum(sym,GRID_TS[ei],GRID_TS[xi])

# ---- signals: realistic-fill re-sim at T+0 ----
bysym={}
for s in SIGS: bysym.setdefault(s['sym'],[]).append(s)
rng=np.random.default_rng(20260822)
sig_real=[]; base=[]; base_nofilt=[]
for k,sym in enumerate(KEEP):
    O,H,L,C,QV=regrid(*load(sym))
    csum=np.nancumsum(np.nan_to_num(QV))
    qv24=np.full(N,np.nan); qv24[287:]=csum[287:]-np.concatenate(([0.0],csum[:-288]))
    for s in bysym.get(sym,[]):
        ei=s['sig_i']+1
        if np.isnan(O[ei]): continue
        px,xi,kd=sim(O,H,L,C,ei,O[ei])
        sig_real.append(dict(sym=sym,ts=s['ts'],pnl=pnl(sym,O[ei],px,ei,xi,kd),kind=kd,btc30=s['btc30']))
    elig=np.where((qv24>=MIN_QV)&~np.isnan(O)&(np.arange(N)<N-HOLD_BARS-1)&(np.arange(N)>=288))[0]
    if len(elig)==0: continue
    er=elig[REGIME_OK[elig]]
    for pool,dst in ((er,base),(elig,base_nofilt)):
        if len(pool)==0: continue
        for ei in rng.choice(pool,size=min(25,len(pool)),replace=False):
            ei=int(ei); px,xi,kd=sim(O,H,L,C,ei,O[ei])
            dst.append(dict(sym=sym,ts=int(GRID_TS[ei]),pnl=pnl(sym,O[ei],px,ei,xi,kd),kind=kd))
    if k%100==0: print(k,sym,len(sig_real),len(base),flush=True)
pickle.dump(dict(sig=sig_real,base=base,base_nofilt=base_nofilt),open('baseline.pkl','wb'))
print('done',len(sig_real),len(base),len(base_nofilt))
