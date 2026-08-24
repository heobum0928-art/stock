"""Extend 5m klines through 2026-08-23 using daily zips; write pqx/<sym>.npz = pq + Aug."""
import requests, io, zipfile, json, os, time, glob
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
D=os.path.dirname(os.path.abspath(__file__))
BASE="https://data.binance.vision/data/futures/um/daily/klines/{s}/5m/{s}-5m-{d}.zip"
DAYS=[f"2026-08-{d:02d}" for d in range(1,24)]
COLS=["open_time","open","high","low","close","volume","close_time","quote_volume","count","tb","tbq","ig"]
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(D,"pq","*.npz")))
sess=requests.Session()
def one(s):
    out=os.path.join(D,"pqx",s+".npz")
    if os.path.exists(out): return (s,-1)
    frames=[]
    for dd in DAYS:
        r=None
        for _ in range(3):
            try:
                r=sess.get(BASE.format(s=s,d=dd),timeout=60); break
            except Exception:
                time.sleep(2)
        if r is None or r.status_code!=200: continue
        try:
            z=zipfile.ZipFile(io.BytesIO(r.content)); n=z.namelist()[0]; raw=z.read(n)
            hdr=0 if raw[:9].decode(errors='replace').startswith('open_time') else None
            df=pd.read_csv(io.BytesIO(raw),header=hdr,names=None if hdr==0 else COLS)
        except Exception:
            continue
        frames.append(df[["open_time","open","high","low","close","quote_volume"]].copy())
    z0=np.load(os.path.join(D,"pq",s+".npz"))
    base=pd.DataFrame({"open_time":z0["t"],"open":z0["o"],"high":z0["h"],"low":z0["l"],"close":z0["c"],"quote_volume":z0["qv"]})
    d=pd.concat([base]+frames,ignore_index=True) if frames else base
    d=d.astype({"open_time":"int64","open":"float64","high":"float64","low":"float64","close":"float64","quote_volume":"float64"})
    d=d.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    np.savez_compressed(out,t=d["open_time"].to_numpy(),o=d["open"].to_numpy(),h=d["high"].to_numpy(),
                        l=d["low"].to_numpy(),c=d["close"].to_numpy(),qv=d["quote_volume"].to_numpy())
    return (s,len(d),len(frames))
if __name__=="__main__":
    n=0
    with ThreadPoolExecutor(max_workers=16) as ex:
        for i,r in enumerate(ex.map(one,syms)):
            n+=1
            if i%50==0: print(i,r,flush=True)
    print("DONE",n)
