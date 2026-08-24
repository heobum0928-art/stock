import requests, json, io, zipfile, os, sys, numpy as np
from concurrent.futures import ThreadPoolExecutor

KEEP=json.load(open('keep_syms.json'))
MONTHS=['2025-08','2025-09','2025-10','2025-11','2025-12','2026-01','2026-02','2026-03','2026-04','2026-05','2026-06','2026-07']
DAYS=[f'2026-08-{d:02d}' for d in range(1,22)]
OUT='data'
os.makedirs(OUT,exist_ok=True)
BASE='https://data.binance.vision/data/futures/um'

def parse(content, rows):
    z=zipfile.ZipFile(io.BytesIO(content))
    with z.open(z.namelist()[0]) as f:
        for line in io.TextIOWrapper(f,'utf-8'):
            c=line.split(',')
            try: ts=int(float(c[0]))
            except ValueError: continue
            if ts>1e14: ts//=1000  # microsecond timestamps in newer dumps
            rows.append((ts,float(c[1]),float(c[2]),float(c[3]),float(c[4]),float(c[7])))

def work(sym):
    p=f'{OUT}/{sym}.npz'
    if os.path.exists(p): return sym,-1
    s=requests.Session(); rows=[]
    for m in MONTHS:
        try:
            r=s.get(f'{BASE}/monthly/klines/{sym}/5m/{sym}-5m-{m}.zip',timeout=60)
            if r.status_code==200: parse(r.content,rows)
        except Exception: pass
    for d in DAYS:
        try:
            r=s.get(f'{BASE}/daily/klines/{sym}/5m/{sym}-5m-{d}.zip',timeout=60)
            if r.status_code==200: parse(r.content,rows)
        except Exception: pass
    if not rows: return sym,0
    rows.sort()
    a=np.array(rows,dtype=np.float64)
    _,idx=np.unique(a[:,0],return_index=True)
    a=a[idx]
    np.savez_compressed(p, ts=a[:,0].astype(np.int64),
        o=a[:,1].astype(np.float32),h=a[:,2].astype(np.float32),
        l=a[:,3].astype(np.float32),c=a[:,4].astype(np.float32),
        qv=a[:,5].astype(np.float32))
    return sym,len(a)

done=0
with ThreadPoolExecutor(20) as ex:
    for sym,n in ex.map(work,KEEP):
        done+=1
        if done%50==0: print(done,sym,n,flush=True)
print('DONE')
