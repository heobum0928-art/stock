import requests, io, zipfile, json, os, sys, time
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
BASE="https://data.binance.vision/data/futures/um/monthly/klines/{s}/5m/{s}-5m-{m}.zip"
MONTHS=[f"{y}-{mm:02d}" for y in (2025,2026) for mm in range(1,13)]
MONTHS=[m for m in MONTHS if "2025-07"<=m<="2026-07"]
syms=json.load(open("all_um_usdt_syms.json"))
os.makedirs("pq",exist_ok=True)
sess=requests.Session()
COLS=["open_time","open","high","low","close","volume","close_time","quote_volume","count","tb","tbq","ig"]
def one(s):
    out="pq/%s.npz"%s
    if os.path.exists(out): return (s,-1)
    frames=[]
    for m in MONTHS:
        for attempt in range(3):
            try:
                r=sess.get(BASE.format(s=s,m=m),timeout=60)
                break
            except Exception:
                time.sleep(2); r=None
        if r is None or r.status_code!=200: continue
        try:
            z=zipfile.ZipFile(io.BytesIO(r.content))
            n=z.namelist()[0]
            raw=z.read(n)
            hdr=0 if raw[:9].decode(errors='replace').startswith('open_time') else None
            df=pd.read_csv(io.BytesIO(raw),header=hdr,names=None if hdr==0 else COLS)
        except Exception:
            continue
        df=df[["open_time","open","high","low","close","quote_volume"]].copy()
        frames.append(df)
    if not frames: return (s,0)
    d=pd.concat(frames,ignore_index=True)
    d=d.astype({"open_time":"int64","open":"float64","high":"float64","low":"float64","close":"float64","quote_volume":"float64"})
    d=d.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    import numpy as _np
    _np.savez_compressed(out, t=d["open_time"].to_numpy(), o=d["open"].to_numpy(), h=d["high"].to_numpy(), l=d["low"].to_numpy(), c=d["close"].to_numpy(), qv=d["quote_volume"].to_numpy())
    return (s,len(d))
if __name__=="__main__":
    res=[]
    with ThreadPoolExecutor(max_workers=24) as ex:
        for i,r in enumerate(ex.map(one,syms)):
            res.append(r)
            if i%50==0: print(i,r,flush=True)
    ok=[r for r in res if r[1]>0 or r[1]==-1]
    print("done, with data:",len([r for r in res if r[1]!=0]))
