"""정정: 룩어헤드 제거 국면(키 d-31..d-2) — #40b/#41b"""
import glob,os,json,datetime as dt,numpy as np,collections
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT','BTCUSDT','ETHUSDT'}
def full(dirn):
    D={}
    for f in glob.glob(S+dirn+'/d_*.json'):
        s=os.path.basename(f)[2:-5]
        if s in EX: continue
        D[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(k[4],k[5]) for k in json.load(open(f))}
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
    return out   # 키 d: d 종가→d+1 종가 수익
# 기간별 바구니(수익은 d→d+1이므로 d일 진입 전 정보는 d-30..d-1 키의 수익 = 어제까지)
Bd={}
for f in sorted(glob.glob('research/m5bt/pq_bull/*.npz')):
    s=os.path.basename(f)[:-4]
    if s in EX: continue
    z=np.load(f);t=z['t']//1000;day=t//86400;u,idx=np.unique(day,return_index=True);e=np.r_[idx[1:],len(t)]
    Bd[s]={dt.date(1970,1,1)+dt.timedelta(int(a)):(z['c'][b-1],z['qv'][i:b].sum()) for a,i,b in zip(u,idx,e)}
BK={'C':basket(full('nr7hC'),dt.date(2021,1,15),dt.date(2022,12,30)),'B':basket(Bd,dt.date(2023,1,15),dt.date(2025,6,29)),'A':basket(full('nr7h'),dt.date(2024,12,31),dt.date(2026,9,29))}
EV={'C':json.load(open(S+'ext_C.json')),'B':json.load(open(S+'ext_B.json')),'A':json.load(open(S+'ext_A.json'))}
rows=[];dump=[]
for p,ev in EV.items():
    bk=BK[p]
    for (d,s,sd,rs,rc,adv,adv_stop) in ev:
        if sd!='S': continue
        dd=dt.date.fromisoformat(d);r=[bk.get(dd-dt.timedelta(i)) for i in range(2,32)]
        if any(x is None for x in r): continue
        reg=np.prod([1+x for x in r])-1
        rows.append((p,dd.toordinal(),reg,rs-0.0012));dump.append([p,d,s,sd,rs,rc,adv,adv_stop,float(reg)])
P=np.array([r[0] for r in rows]);Dd=np.array([r[1] for r in rows]);Rg=np.array([r[2] for r in rows]);X=np.array([r[3] for r in rows])
up=Rg>0
print(f'확보 {len(X)}건')
for p in 'CBA':
    m=P==p;a=X[m&up];b=X[m&~up];days=len(set(Dd[m&up]))+len(set(Dd[m&~up]))
    print(f'기간 {p}: 상승국면 n={len(a)} 평균 {a.mean()*100 if len(a) else float("nan"):+.3f}% 승률 {(a>0).mean()*100 if len(a) else 0:.0f}% | 하락국면 n={len(b)} 평균 {b.mean()*100 if len(b) else float("nan"):+.3f}% 승률 {(b>0).mean()*100 if len(b) else 0:.0f}% | 상승국면 건 비율 {up[m].mean()*100:.0f}%')
days=np.unique(Dd);idx={d:np.nonzero(Dd==d)[0] for d in days};rng=np.random.default_rng(20261003);ds=[]
for _ in range(4000):
    sel=np.concatenate([idx[days[q]] for q in rng.integers(0,len(days),len(days))])
    a=X[sel][~up[sel]];b=X[sel][up[sel]]
    if len(a) and len(b): ds.append(a.mean()-b.mean())
lo,hi=np.percentile(ds,[2.5,97.5]);df=X[~up].mean()-X[up].mean()
print(f'풀링 차이(하락−상승) {df*100:+.3f}%p  95% CI [{lo*100:+.3f},{hi*100:+.3f}]')
sign=all((X[(P==p)&~up].mean()>X[(P==p)&up].mean()) for p in 'CBA' if ((P==p)&up).sum()>=30 and ((P==p)&~up).sum()>=30)
print('각 기간 같은 부호(하락>상승):',sign)
print('판정:','성립' if df>0 and lo>0 and sign else '기각')

json.dump(dump,open(S+'ext_regime2.json','w'));print('저장',len(dump))
