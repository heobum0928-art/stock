import requests, json, os, time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
syms=json.load(open("all_um_usdt_syms.json"))
os.makedirs("fund",exist_ok=True)
S=1751328000000  # 2025-07-01
E=1754006400000+ 0
E=1785000000000
sess=requests.Session()
def one(s):
    out="fund/%s.npz"%s
    if os.path.exists(out): return 0
    rows=[]; st=S
    for _ in range(6):
        try:
            r=sess.get("https://fapi.binance.com/fapi/v1/fundingRate",params={"symbol":s,"startTime":st,"limit":1000},timeout=30)
        except Exception:
            time.sleep(3); continue
        if r.status_code!=200: break
        j=r.json()
        if not j: break
        rows+=j
        nt=j[-1]["fundingTime"]+1
        if nt<=st or len(j)<1000: break
        st=nt
    if not rows: return 0
    d=pd.DataFrame(rows)[["fundingTime","fundingRate"]]
    d["fundingTime"]=d["fundingTime"].astype("int64"); d["fundingRate"]=d["fundingRate"].astype(float)
    d=d.drop_duplicates("fundingTime").sort_values("fundingTime")
    import numpy as _np
    _np.savez_compressed(out, t=d["fundingTime"].to_numpy(), r=d["fundingRate"].to_numpy())
    return len(d)
if __name__=="__main__":
    n=0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i,r in enumerate(ex.map(one,syms)):
            n+=1
            if i%100==0: print(i,r,flush=True)
    print("done")
