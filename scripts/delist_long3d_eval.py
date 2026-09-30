"""prereg #15 PREREG_DELIST_LONG3D.md (delist_drift_eval 복제, 지평 3일 롱)"""
import json,re,io,zipfile,csv,sys,requests,datetime as dt,numpy as np
S=sys.argv[1]
a=json.load(open(S))
sp=[x for x in a if re.match(r'Binance Will Delist [A-Z0-9, and]+ on \d{4}',x['title'])]
cache={}
def month_closes(kind,sym,y,m):
    k=(kind,sym,y,m)
    if k in cache: return cache[k]
    base='spot' if kind=='spot' else 'futures/um'
    u=f'https://data.binance.vision/data/{base}/monthly/klines/{sym}/1d/{sym}-1d-{y}-{m:02d}.zip'
    out={}
    try:
        r=requests.get(u,timeout=30)
        if r.status_code==200 and len(r.content)>400:
            z=zipfile.ZipFile(io.BytesIO(r.content))
            for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                try: t=int(row[0])
                except: continue
                while t>1e13: t//=1000
                out[dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).date()]=float(row[4])
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
    btc=closes('spot','BTCUSDT',ann,de+dt.timedelta(8))
    for t in toks:
        c=closes('spot',t+'USDT',ann,de+dt.timedelta(8))
        if ann not in c or ann not in btc: continue
        res={}
        for h in (1,3,7):
            e=ann+dt.timedelta(h)
            cand=[d for d in c if ann<d<=min(e,de)]
            if not cand: break
            l=max(cand)
            if l not in btc: break
            res[h]=(c[l]/c[ann]-1-0.0012,(c[l]/c[ann]-1)-(btc[l]/btc[ann]-1))
        if 3 in res: obs.append((x['id'],ann.year,res[3][0],res[3][1],res.get(1),res.get(7),t,str(ann)))
n=len(obs);print('관측',n)
if n:
    r=np.array([o[2] for o in obs]);ev=np.array([o[0] for o in obs]);ids=np.unique(ev);g={i:r[ev==i] for i in ids};rng=np.random.default_rng(20260930)
    ms=[np.concatenate([g[k] for k in rng.choice(ids,len(ids))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    print(f'3일 순수익 평균 {r.mean()*100:+.2f}% 중앙 {np.median(r)*100:+.2f}% 승률 {(r>0).mean()*100:.0f}% CI [{lo*100:+.2f},{hi*100:+.2f}] 이벤트 {len(ids)}  BTC초과 평균 {np.mean([o[3] for o in obs])*100:+.2f}%')
    print(f'최대이익 {r.max()*100:+.1f}% 최대손실 {r.min()*100:+.1f}%  상위5 이익 비중 {np.sort(r)[::-1][:5].sum()/r[r>0].sum()*100:.0f}%')
    o1=[o[4][0] for o in obs if o[4]];o7=[o[5][0] for o in obs if o[5]]
    print(f'병기 1일 평균 {np.mean(o1)*100:+.2f}% (n={len(o1)})  7일 평균 {np.mean(o7)*100:+.2f}% (n={len(o7)})')
    for y in sorted(set(o[1] for o in obs)):
        m=np.array([o[1]==y for o in obs]);print(f'  {y}: n={m.sum()} {r[m].mean()*100:+.2f}%')
    print('판정:', '판별 불가' if n<100 else ('성립' if r.mean()>0 and lo>0 else '기각'))
