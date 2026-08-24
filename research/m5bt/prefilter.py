import requests, json, io, zipfile, csv, sys
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET

pfx='data/futures/um/monthly/klines/'
tok=None; syms=[]
ns='{http://s3.amazonaws.com/doc/2006-03-01/}'
while True:
    p={'delimiter':'/','prefix':pfx}
    if tok: p['marker']=tok
    r=requests.get('https://s3-ap-northeast-1.amazonaws.com/data.binance.vision',params=p,timeout=30)
    root=ET.fromstring(r.text)
    cps=[e.find(ns+'Prefix').text for e in root.findall(ns+'CommonPrefixes')]
    syms+=[c[len(pfx):-1] for c in cps]
    if root.find(ns+'IsTruncated').text!='true': break
    tok=cps[-1]
syms=[s for s in syms if s.endswith('USDT')]
json.dump(syms, open('all_syms.json','w'))
print('universe dirs', len(syms), flush=True)

MONTHS=['2025-08','2025-09','2025-10','2025-11','2025-12','2026-01','2026-02','2026-03','2026-04','2026-05','2026-06','2026-07']
sess=requests.Session()

def dayinfo(sym):
    # monthly 1d klines over window -> max quote volume; plus first-ever data month
    maxqv=0.0; nrows=0
    for m in MONTHS:
        u=f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{m}.zip'
        try:
            r=sess.get(u,timeout=30)
        except Exception:
            continue
        if r.status_code!=200: continue
        try:
            z=zipfile.ZipFile(io.BytesIO(r.content))
            with z.open(z.namelist()[0]) as f:
                for line in io.TextIOWrapper(f,'utf-8'):
                    c=line.split(',')
                    if not c[0].replace('.','').isdigit(): continue
                    nrows+=1
                    qv=float(c[7])
                    if qv>maxqv: maxqv=qv
        except Exception: pass
    return sym,maxqv,nrows

out={}
with ThreadPoolExecutor(24) as ex:
    for i,(s,q,n) in enumerate(ex.map(dayinfo,syms)):
        out[s]={'maxqv':q,'ndays':n}
        if i%100==0: print(i,flush=True)
json.dump(out,open('prefilter.json','w'))
keep=[s for s,v in out.items() if v['maxqv']>=3_000_000 and v['ndays']>0]
print('with data in window:',sum(1 for v in out.values() if v['ndays']>0))
print('keep (ever >=3M qv day):',len(keep))
json.dump(keep,open('keep_syms.json','w'))
