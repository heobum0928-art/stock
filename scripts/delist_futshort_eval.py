"""prereg #14 PREREG_DELIST_FUTSHORT.md (delist_drift_eval 복제 + 선물 다리)"""
import json,re,io,zipfile,csv,sys,requests,datetime as dt,numpy as np
S=sys.argv[1]
a=json.load(open(S))
sp=[x for x in a if re.match(r'Binance Will Delist [A-Z0-9, and]+ on \d{4}',x['title'])]
cache={}
def month_closes(kind,sym,y,m):
    k=(kind,sym,y,m)
    if k in cache: return cache[k]
    base='spot' if kind=='spot' else 'futures/um'
    u=(f'https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip' if kind=='fund' else f'https://data.binance.vision/data/{base}/monthly/klines/{sym}/1d/{sym}-1d-{y}-{m:02d}.zip')
    out={}
    try:
        r=requests.get(u,timeout=30)
        if r.status_code==200 and len(r.content)>400:
            z=zipfile.ZipFile(io.BytesIO(r.content))
            for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                try: t=int(row[0]); v=float(row[2] if kind=='fund' else row[4])
                except: continue
                while t>1e13: t//=1000
                if kind=='fund': out[t]=v
                else: out[dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).date()]=float(row[4])
    except Exception: pass
    cache[k]=out; return out
def closes(kind,sym,d0,d1):
    out={};y,m=d0.year,d0.month
    while (y,m)<=(d1.year,d1.month):
        out.update(month_closes(kind,sym,y,m)); m+=1
        if m>12:y+=1;m=1
    return out
obs=[]
for x in sp:
    ann=dt.datetime.fromtimestamp(x['releaseDate']/1000,dt.timezone.utc).date()
    de=dt.date.fromisoformat(re.search(r'on (\d{4}-\d{2}-\d{2})',x['title']).group(1))
    toks=[w for w in re.split(r'[ ,]+',x['title'].split('Delist ')[1].split(' on ')[0]) if w and w!='and' and w==w.upper()]
    for t in toks:
        f=closes('fut',t+'USDT',ann,de)
        if ann not in f: continue
        cand=[d for d in f if ann<d<=de]
        if not cand: continue
        last=max(cand); r=f[last]/f[ann]-1
        fund=closes('fund',t+'USDT',ann,de); t0=int(dt.datetime.combine(ann,dt.time(0),dt.timezone.utc).timestamp()*1000)+86400000
        t1=int(dt.datetime.combine(last,dt.time(0),dt.timezone.utc).timestamp()*1000)+86400000
        fr=sum(v for k,v in fund.items() if t0<=k<t1)
        net=-r-0.0012+fr
        obs.append((x['id'],ann.year,net,r,fr,last<de,(last-ann).days,t,str(ann)))
n=len(obs);print('관측',n)
for o in sorted(obs,key=lambda o:o[2])[:5]: print('WORST',o)
if n:
    net=np.array([o[2] for o in obs]);ev=np.array([o[0] for o in obs]);ids=np.unique(ev);g={i:net[ev==i] for i in ids};rng=np.random.default_rng(20260930)
    ms=[np.concatenate([g[k] for k in rng.choice(ids,len(ids))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    print(f'순수익 평균 {net.mean()*100:+.2f}% 중앙 {np.median(net)*100:+.2f}% 승률 {(net>0).mean()*100:.0f}% CI [{lo*100:+.2f},{hi*100:+.2f}] 이벤트 {len(ids)}')
    print(f'펀딩 평균 {np.mean([o[4] for o in obs])*100:+.2f}%  선물 조기종료 {np.mean([o[5] for o in obs])*100:.0f}%  평균 보유 {np.mean([o[6] for o in obs]):.1f}일  최악 단일 {net.min()*100:+.1f}%  하위5 합 {np.sort(net)[:5].sum()*100:+.1f}%')
    for y in sorted(set(o[1] for o in obs)):
        m=np.array([o[1]==y for o in obs]);print(f'  {y}: n={m.sum()} 순 {net[m].mean()*100:+.2f}%')
    print('판정:', '판별 불가' if n<50 else ('성립' if net.mean()>0 and lo>0 else '기각'))
if n:
    c=np.maximum(net,-1.0)
    print(f'[사후 기술, 판정 아님] 손실 -100% 캡(1배 청산 근사) 평균 {c.mean()*100:+.2f}% 중앙 {np.median(c)*100:+.2f}%  |  ALPACA 1건 제외 평균 {np.mean([o[2] for o in obs if o[7]!="ALPACA"])*100:+.2f}%  |  가격 +100% 이상 급등 {sum(1 for o in obs if o[3]>=1.0)}건/{n}')
