import requests,json,os,numpy as np
from concurrent.futures import ThreadPoolExecutor
KEEP=json.load(open('keep_syms.json'))
START=int(np.datetime64('2025-07-25').astype('datetime64[ms]').astype(np.int64))
END=int(np.datetime64('2026-08-23').astype('datetime64[ms]').astype(np.int64))
os.makedirs('fund',exist_ok=True)
def work(sym):
    p=f'fund/{sym}.npz'
    if os.path.exists(p): return sym,-1
    s=requests.Session(); out=[]; st=START
    for _ in range(8):
        try:
            r=s.get('https://fapi.binance.com/fapi/v1/fundingRate',
                    params={'symbol':sym,'startTime':st,'endTime':END,'limit':1000},timeout=30)
        except Exception: break
        if r.status_code!=200: break
        j=r.json()
        if not j: break
        out+=[(int(x['fundingTime']),float(x['fundingRate'])) for x in j]
        if len(j)<1000: break
        st=int(j[-1]['fundingTime'])+1
    if out:
        out=sorted(set(out))
        a=np.array(out,dtype=np.float64)
        np.savez_compressed(p,ts=a[:,0].astype(np.int64),r=a[:,1])
    return sym,len(out)
n=0; empty=[]
with ThreadPoolExecutor(8) as ex:
    for sym,k in ex.map(work,KEEP):
        n+=1
        if k==0: empty.append(sym)
        if n%100==0: print(n,flush=True)
print('no funding data:',len(empty))
json.dump(empty,open('nofund.json','w'))
