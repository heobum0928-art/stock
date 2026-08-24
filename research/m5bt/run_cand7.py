import os,numpy as np,pickle,sys
sys.path.insert(0,'.')
import engine as ES, engine_long as EL
D=os.path.dirname(os.path.abspath(__file__)); PQ=os.path.join(D,'pq'); FD=os.path.join(D,'fund')
HOLD=576
_cache={}
def load(sym):
    if sym not in _cache:
        z=np.load(os.path.join(PQ,sym+'.npz')); _cache[sym]=(z['t'],z['o'],z['h'],z['l'],z['c'])
    return _cache[sym]
def cumfund(sym,t0,bt):
    p=os.path.join(FD,sym+'.npz')
    if not os.path.exists(p): return np.zeros(len(bt))
    z=np.load(p); ft=z[z.files[0]]; fr=z[z.files[1]]
    cs=np.concatenate(([0.0],np.cumsum(fr)))
    return cs[np.searchsorted(ft,bt,'right')]-cs[np.searchsorted(ft,t0,'right')]

def run(tag):
    z=np.load('base_%s.npz'%tag,allow_pickle=True)
    syms=z['sym']; t0s=z['t0'].astype(np.int64)
    out={k:[] for k in ('s_ret','l_ret','l_price','l_fund','l_liq','l_kind','s_ret_chk')}
    miss=0
    for sym,t0 in zip(syms,t0s):
        try: t,o,h,l,c=load(str(sym))
        except Exception: miss+=1; continue
        i=int(np.searchsorted(t,t0)); 
        if i>=len(t) or t[i]!=t0: miss+=1; continue
        j=min(i+1+HOLD,len(c))
        if j-(i+1)<12: miss+=1; continue
        sl=slice(i+1,j); P0=float(c[i])
        hh,ll,oo,cc,bt=h[sl],l[sl],o[sl],c[sl],t[sl]
        cf=cumfund(str(sym),int(t0),bt)
        # 숏 재현 (파이프라인 검증)
        f,tr,ex,mae,mfe=ES.scan(hh,ll,oo,cc,P0,opt=True)
        se=ES.SigEvents(f,tr,ex,mae,mfe,P0,int(t0),bt,len(cc)); se.cumfund=cf
        out['s_ret_chk'].append(ES.evaluate(se,None,0.0,40.0,40.0,funding_fn=ES.funding)['ret']*100)
        # 롱
        f2,tr2,ex2,mae2,mfe2=EL.scan(hh,ll,oo,cc,P0,opt=True)
        se2=EL.SigEvents(f2,tr2,ex2,mae2,mfe2,P0,int(t0),bt,len(cc)); se2.cumfund=cf
        r=EL.evaluate(se2,40.0,funding_fn=EL.funding)
        out['l_ret'].append(r['ret']*100); out['l_price'].append(r['price_only']*100)
        out['l_fund'].append(r['fund']*100); out['l_liq'].append(r['liq']); out['l_kind'].append(r['kind'])
    print(f"  [{tag}] 처리 {len(out['l_ret'])}건, 누락 {miss}건")
    return {k:np.array(v) for k,v in out.items() if v}, z

for tag in ('real','rand'):
    d,z=run(tag)
    np.savez('cand7_%s.npz'%tag, sym=z['sym'][:len(d['l_ret'])], hold=z['hold'][:len(d['l_ret'])],
             t0=z['t0'][:len(d['l_ret'])], **d)
    ref=z['ret_opt']*100
    print(f"  숏 원본 평균 {ref.mean():+.3f}  /  내 재현 {d['s_ret_chk'].mean():+.3f}  차이 {d['s_ret_chk'].mean()-ref[:len(d['s_ret_chk'])].mean():+.4f}")
