"""prereg #21 PREREG_TREND200_DEAD.md"""
import io,zipfile,csv,requests,datetime as dt,numpy as np
def series(sym,y0,y1):
    out={}
    for y in range(y0,y1+1):
        for m in range(1,13):
            r=requests.get(f'https://data.binance.vision/data/spot/monthly/klines/{sym}/1d/{sym}-1d-{y}-{m:02d}.zip',timeout=30)
            if r.status_code!=200: continue
            z=zipfile.ZipFile(io.BytesIO(r.content))
            for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
                t=int(row[0])
                while t>1e13: t//=1000
                out[dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).date()]=float(row[4])
    D=sorted(out);return D,np.array([out[d] for d in D])
ok=True
for sym in ('LUNAUSDT','FTTUSDT'):
    D,C=series(sym,2019,2022);n=len(C);ma=np.full(n,np.nan)
    for i in range(199,n): ma[i]=C[i-199:i+1].mean()
    st=np.zeros(n);cur=0
    for i in range(199,n): cur=1 if C[i]>ma[i]*1.01 else (0 if C[i]<ma[i]*0.99 else cur); st[i]=cur
    pos=np.r_[0,st[:-1]];ret=np.r_[0,C[1:]/C[:-1]-1]
    r=(pos*ret-np.r_[0,np.abs(np.diff(pos))]*0.001)[199:];h=ret[199:]
    f=lambda x:(np.cumprod(1+x)[-1],(np.cumprod(1+x)/np.maximum.accumulate(np.cumprod(1+x))-1).min())
    a,b=f(r),f(h);ok&=a[1]>-0.5
    crash=int(np.argmin(ret));print(f'{sym} {D[199]}~{D[-1]}: 규칙 {a[0]:.2f}배 MDD {a[1]:.0%} | 보유 {b[0]:.2f}배 MDD {b[1]:.0%} | 최대 하락일 {D[crash]} {ret[crash]:.0%} 그날 규칙 {"ON" if pos[crash] else "OFF"}')
print('판정:','성립' if ok else '기각')
