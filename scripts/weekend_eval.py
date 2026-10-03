"""prereg #37 PREREG_WEEKEND_SHORT.md"""
import glob,os,json,datetime as dt,numpy as np
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT','BTCUSDT','ETHUSDT'}
def load_cache(dirn):
    D={}
    for f in glob.glob(S+dirn+'/*.json'):
        s=os.path.basename(f)[:-5]
        if s in EX or s.endswith('_f'): continue
        try: v=json.load(open(f))
        except Exception: continue
        if v and len(v[0])>=3 and isinstance(v[0][0],int) and not isinstance(v[0][1],list): D[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(k[1],k[2]) for k in v}
    return D
def load_full(dirn):  # nr7h/d_*.json: (t,o,h,l,c,qv)
    D={}
    for f in glob.glob(S+dirn+'/d_*.json'):
        s=os.path.basename(f)[2:-5]
        if s in EX: continue
        v=json.load(open(f));D[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(k[4],k[5]) for k in v}
    return D
def basket(D,d0,d1):
    out={};d=d0
    while d<=d1:
        vols={}
        for s,v in D.items():
            w=[v.get(d-dt.timedelta(i)) for i in range(1,31)]
            if all(w) and d in v and d+dt.timedelta(1) in v: vols[s]=sum(x[1] for x in w)
        top=sorted(vols,key=vols.get,reverse=True)[:20]
        if len(top)>=10: out[d]=np.mean([D[s][d+dt.timedelta(1)][0]/D[s][d][0]-1 for s in top])
        d+=dt.timedelta(1)
    return out
# 기간 A: nr7h/d_*.json(2024-12~), C: altC/*.json(2020-10~) , B: pq_bull 일봉(5분봉 집계)
A=basket(load_full('nr7h'),dt.date(2025,1,1),dt.date(2026,9,29))
C={}
try:
    from glob import glob as g
    DC={}
    for f in g(S+'nr7hC/d_*.json'):
        s=os.path.basename(f)[2:-5]
        if s in EX: continue
        v=json.load(open(f));DC[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(k[4],k[5]) for k in v}
    C=basket(DC,dt.date(2021,3,1),dt.date(2022,12,30))
except Exception as e: print('C 로드 실패',e)
# B
Bd={}
for f in sorted(glob.glob('research/m5bt/pq_bull/*.npz')):
    s=os.path.basename(f)[:-4]
    if s in EX: continue
    z=np.load(f);t=z['t']//1000;day=t//86400;u,idx=np.unique(day,return_index=True);e=np.r_[idx[1:],len(t)]
    Bd[s]={dt.date(1970,1,1)+dt.timedelta(int(a)):(z['c'][b-1],z['qv'][i:b].sum()) for a,i,b in zip(u,idx,e)}
B=basket(Bd,dt.date(2023,2,1),dt.date(2024,12,31))
def split(x):
    wk=[(d,v) for d,v in x.items() if d.weekday()>=5];wd=[(d,v) for d,v in x.items() if d.weekday()<5]
    return wk,wd
allw=[];allwd=[];ok=True
for nm,x in (('C 2021-03~2022-12',C),('B 2023-02~2024-12',B),('A 2025-01~2026-09',A)):
    if not x: print(nm,'데이터 없음');ok=False;continue
    wk,wd=split(x);mw=np.mean([v for _,v in wk]);md=np.mean([v for _,v in wd])
    sat=np.mean([v for d,v in wk if d.weekday()==5]);sun=np.mean([v for d,v in wk if d.weekday()==6])
    print(f'{nm}: 일수 {len(x)} 주말 평균 {mw*100:+.3f}%/일 평일 {md*100:+.3f}%/일 차이 {(mw-md)*100:+.3f}%p (토 {sat*100:+.3f} 일 {sun*100:+.3f})')
    ok&=mw<md;allw+=wk;allwd+=wd
# 주 단위 부트스트랩: 주별 (주말평균−평일평균)
bywk={}
for nm,x in (('C',C),('B',B),('A',A)):
    for d,v in x.items(): bywk.setdefault((nm,d.isocalendar()[:2]),[[],[]])[0 if d.weekday()>=5 else 1].append(v)
diffs=np.array([np.mean(a)-np.mean(b) for a,b in bywk.values() if a and b]);rng=np.random.default_rng(20261003)
ms=[diffs[rng.integers(0,len(diffs),len(diffs))].mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
print(f'주 {len(diffs)}개 평균 차이(주말−평일) {diffs.mean()*100:+.3f}%p/일 CI [{lo*100:+.3f},{hi*100:+.3f}]')
# 금 종가 숏→월 종가 청산(단순)
print('판정:','성립' if ok and hi<0 else '기각')
