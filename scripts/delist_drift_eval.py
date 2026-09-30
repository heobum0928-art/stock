"""prereg #13 PREREG_DELIST_DRIFT.md"""
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
    toks=re.findall(r'\b[A-Z0-9]{2,10}\b',x['title'].split('Delist ')[1].split(' on ')[0].replace(' and ',','))
    btc=closes('spot','BTCUSDT',ann,de)
    for t in toks:
        c=closes('spot',t+'USDT',ann,de)
        if ann not in c or ann not in btc: continue
        last=max(d for d in c if d<=de)
        if last<=ann or last not in btc: continue
        r=c[last]/c[ann]-1; b=btc[last]/btc[ann]-1
        fut=bool(closes('fut',t+'USDT',ann,ann))
        obs.append((x['id'],ann.year,r,r-b,fut))
n=len(obs);ex=np.array([o[3] for o in obs]);ab=np.array([o[2] for o in obs]);ev=np.array([o[0] for o in obs])
print(f'관측 토큰 {n}, 이벤트 {len(set(ev))}')
if n:
    ids=np.unique(ev);g={i:ex[ev==i] for i in ids};rng=np.random.default_rng(20260930)
    ms=[np.concatenate([g[k] for k in rng.choice(ids,len(ids))]).mean() for _ in range(4000)];lo,hi=np.percentile(ms,[2.5,97.5])
    print(f'초과수익 평균 {ex.mean()*100:+.2f}% 중앙 {np.median(ex)*100:+.2f}% 하락비율 {(ex<0).mean()*100:.0f}%  95% CI [{lo*100:+.2f},{hi*100:+.2f}]  절대수익 평균 {ab.mean()*100:+.2f}%')
    for y in sorted(set(o[1] for o in obs)):
        m=np.array([o[1]==y for o in obs]);print(f'  {y}: n={m.sum()} 초과 {ex[m].mean()*100:+.2f}%')
    f=np.array([o[4] for o in obs]);print(f'선물 존재 {f.sum()}/{n} ({f.mean()*100:.0f}%)  선물 있는 토큰 초과 {ex[f].mean()*100 if f.any() else float("nan"):+.2f}%')
    print('판정:', '판별 불가' if n<100 else ('성립' if ex.mean()<0 and hi<0 else '기각'))
