"""롱 엔진 — engine.py(숏)의 정확한 거울상.
숏: 역행=가격상승, 유리=가격하락 / 롱: 역행=가격하락, 유리=가격상승
"""
import numpy as np
HOLD_BARS=576; TRAIL_TRIG=15.0; TRAIL_GIVE=10.0; LEV=2.0
FEE_SIDE=0.0006; STOP_EXTRA=0.0005; MMR=0.05

def liq_adverse_pct(L=LEV, mmr=MMR):
    """롱 청산: r=(L-1)/(L*(1-mmr)) -> 하락률 %"""
    r=(L-1)/(L*(1-mmr))
    return (1-r)*100                    # L=2,mmr=.05 -> 47.368

LEVELS=[8.,12.,16.,20.,25.,30.,40., liq_adverse_pct()]

def scan(h,l,o,c,P0,opt=True,levels=LEVELS):
    """levels[k] = 하락률 %. found[k]=(order,bar,fill) 최초 도달.
    opt=True(낙관): 봉내 순서 o->h->l->c (유리한 쪽 먼저)"""
    n=len(c); nl=len(levels)
    lvlp=[P0*(1-x/100) for x in levels]   # 하락 목표가 (P0보다 낮음, 내림차순)
    found=[None]*nl; lo_i=0
    trail_ev=None; peak_fav=0.0; mae=0.0; order=0; prev=P0
    for i in range(n):
        oi=o[i]; hi=h[i]; li=l[i]; ci=c[i]
        a=(1-li/P0)*100                    # 롱 역행 = 저가 기준 하락폭
        if a>mae: mae=a
        path=(oi,hi,li,ci) if opt else (oi,li,hi,ci)
        for k in range(4):
            nxt=path[k]
            if nxt<prev:                    # 하락 = 롱에 역행
                if trail_ev is None and peak_fav>=TRAIL_TRIG:
                    tl=P0*(1+(peak_fav-TRAIL_GIVE)/100)   # P0보다 높음
                    if tl>=prev: trail_ev=(order,i,prev)
                    elif tl>=nxt: trail_ev=(order,i, nxt if k==0 else tl)
                gap=(k==0)
                j=lo_i
                while j<nl:
                    if found[j] is None:
                        lp=lvlp[j]
                        if lp>=prev: found[j]=(order,i,prev)
                        elif lp>=nxt: found[j]=(order,i, nxt if gap else lp)
                        else: break
                    j+=1
                while lo_i<nl and found[lo_i] is not None: lo_i+=1
            else:
                f=(nxt/P0-1)*100
                if f>peak_fav: peak_fav=f
            prev=nxt; order+=1
        if trail_ev is not None and lo_i>=nl: break
    expiry=(10**9,n-1,c[n-1])
    return found,trail_ev,expiry,mae,peak_fav

class SigEvents:
    __slots__=("found","trail","expiry","mae","mfe","P0","t0","bt","nbars","cumfund")
    def __init__(s,f,tr,ex,mae,mfe,P0,t0,bt,nb):
        s.found=f;s.trail=tr;s.expiry=ex;s.mae=mae;s.mfe=mfe;s.P0=P0;s.t0=t0;s.bt=bt;s.nbars=nb;s.cumfund=None

LIQ_IDX=len(LEVELS)-1; IDX={v:i for i,v in enumerate(LEVELS)}

def evaluate(se, F, funding_fn=None):
    """F: 손절 하락률 %. 단일 손절만(단계청산 없음)."""
    liq=se.found[LIQ_IDX]; eF=se.found[IDX[F]]; tr=se.trail; exp=se.expiry; BIG=10**9
    def key(e):
        # 한 번의 하락 구간 내에서는 가격이 내림차순으로 닿는다.
        # 트레일링선은 P0보다 위, 손절선들은 P0보다 아래 -> 가격 내림차순이 곧 도달순
        return (BIG+1,0.0) if e is None else (e[0], -e[2])
    cands=[(key(eF),eF,'stop'),(key(tr),tr,'trail'),(key(liq),liq,'liq'),(key(exp),exp,'expiry')]
    cands.sort(key=lambda x:x[0])
    fin=cands[0]
    w,P,kind,bi=1.0, fin[1][2], fin[2], fin[1][1]
    tot=-LEV*FEE_SIDE
    tot+= LEV*(P/se.P0-1)                 # 롱: 부호 +
    tot-= LEV*FEE_SIDE
    if kind!='expiry': tot-=LEV*STOP_EXTRA
    fund=0.0
    if funding_fn is not None:
        fund=funding_fn(se,bi); tot+=fund
    liq_flag = (kind=='liq') or (P <= se.P0*(1-LEVELS[LIQ_IDX]/100)*1.0000001)
    if liq_flag: tot=-1.0
    if tot<-1.0: tot=-1.0; liq_flag=True
    return {"ret":tot,"liq":liq_flag,"kind":kind,"exit_bar":bi,"fund":fund,
            "price_only": LEV*(P/se.P0-1)}

def funding(se, bi):
    """롱은 펀딩 부호가 숏의 반대."""
    if se.cumfund is None: return 0.0
    return -LEV*float(se.cumfund[bi])
