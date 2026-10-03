import requests, numpy as np, datetime as dt
D="""2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16""".split()
def ms(t): return int(t.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
px={}
t=dt.datetime(2021,1,1)
while t<dt.datetime(2026,10,1):
    r=requests.get("https://fapi.binance.com/fapi/v1/klines",params=dict(symbol="BTCUSDT",interval="1h",startTime=ms(t),limit=1500)).json()
    for k in r: px[k[0]]=float(k[1])
    t+=dt.timedelta(hours=1500)
def hr(d):
    d=dt.datetime.fromisoformat(d); h=18 if 3<=d.month<=10 and not (d.month==3 and d.day<14) and not(d.month==10 and d.day>31) else 19
    # 미국 서머타임: 3월 둘째 일요일~11월 첫째 일요일 근사 -> 정확 계산
    import calendar
    def nth_sun(y,m,n):
        c=[x for x in range(1,32) if x<=calendar.monthrange(y,m)[1] and dt.date(y,m,x).weekday()==6]; return c[n-1]
    s=dt.date(d.year,3,nth_sun(d.year,3,2)); e=dt.date(d.year,11,nth_sun(d.year,11,1))
    h=18 if s<=d.date()<e else 19
    return d.replace(hour=h)
rets=[];dates=[]
for d in D:
    T=hr(d); a=px.get(ms(T-dt.timedelta(hours=24))); b=px.get(ms(T))
    if a and b: rets.append((b/a-1)*100-0.10); dates.append(d)
r=np.array(rets); print("n",len(r),"mean",r.mean(),"median",np.median(r),"win",(r>0).mean())
rng=np.random.default_rng(0); bs=[rng.choice(r,len(r)).mean() for _ in range(10000)]
print("CI",np.percentile(bs,[2.5,97.5]))
h=[x<'2024' for x in dates]; print("전반",r[np.array(h)].mean(),"후반",r[~np.array(h)].mean())
ks=sorted(px); v=np.array([px[k] for k in ks]); ra=(v[24:]/v[:-24]-1)*100-0.10
print("무작위24h 평균",ra.mean())
