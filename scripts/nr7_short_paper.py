"""모의 전용 — 알트 NR7 숏 (PREREG_NR7_SHORT_PAPER.md). 주문 API 없음, 공개 시세 조회만.
사용: 인자 없으면 기록된 마지막 날 다음 날부터 어제(UTC)까지 보충. 날짜 인자(YYYY-MM-DD)를 주면 그 날만."""
import sys, os, csv, datetime as dt, time, requests
F='https://fapi.binance.com'; TR='data/nr7_short_paper_trades.csv'
EX={'USDCUSDT','FDUSDUSDT','USDEUSDT','BTCDOMUSDT','BTCUSDT','ETHUSDT'}
def ms(d): return int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp()*1000)
def get(path,**p):
    for _ in range(3):
        try:
            r=requests.get(F+path,params=p,timeout=30).json()
            if isinstance(r,(list,dict)) and not (isinstance(r,dict) and 'code' in r): return r
        except Exception: pass
        time.sleep(1)
    return None
perps=[s['symbol'] for s in get('/fapi/v1/exchangeInfo')['symbols'] if s['quoteAsset']=='USDT' and s['contractType']=='PERPETUAL' and s['symbol'] not in EX and s.get('status')=='TRADING']
done=set();last=None
if os.path.exists(TR):
    for r in csv.DictReader(open(TR,encoding='utf-8')):
        done.add((r['date'],r['symbol'])); last=max(last or r['date'],r['date'])
yday=dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(1)
if len(sys.argv)>1: days=[dt.date.fromisoformat(sys.argv[1])]
else:
    start=dt.date.fromisoformat(last)+dt.timedelta(1) if last else yday
    days=[start+dt.timedelta(i) for i in range((yday-start).days+1)]
if not days: print('보충할 날 없음'); sys.exit()
first=min(days)-dt.timedelta(40)
D={}
for s in perps:
    r=get('/fapi/v1/klines',symbol=s,interval='1d',startTime=ms(first),endTime=ms(max(days))+86399999,limit=100)
    if r: D[s]={dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).date():(float(k[2]),float(k[3]),float(k[4]),float(k[7])) for k in r}
new=not os.path.exists(TR)
with open(TR,'a',newline='',encoding='utf-8') as f:
    w=csv.writer(f)
    if new: w.writerow(['date','symbol','side','entry','exit','exit_reason','net_pnl_pct_notional'])
    for d in days:
        vols={}
        for s,v in D.items():
            x=[v.get(d-dt.timedelta(i)) for i in range(1,31)]
            if all(x): vols[s]=sum(a[3] for a in x)
        for s in sorted(vols,key=vols.get,reverse=True)[:20]:
            v=D[s];rg=[(v[d-dt.timedelta(i)][0]-v[d-dt.timedelta(i)][1])/v[d-dt.timedelta(i)][2] for i in range(1,8) if (d-dt.timedelta(i)) in v]
            if len(rg)<7 or rg[0]!=min(rg) or (d.isoformat(),s) in done: continue
            hi,lo=v[d-dt.timedelta(1)][0],v[d-dt.timedelta(1)][1]
            hb=get('/fapi/v1/klines',symbol=s,interval='1h',startTime=ms(d),endTime=ms(d)+86399999,limit=24)
            if not hb or len(hb)<20: continue
            hb=[(float(k[2]),float(k[3]),float(k[4])) for k in hb]
            side=None
            for h,l,c in hb:
                up,dn=h>hi,l<lo
                if up and dn: side='skip';break
                if up: side='L';break
                if dn: side='S';break
            if side in (None,'skip'): continue
            entry=hi if side=='L' else lo;stop=lo if side=='L' else hi;started=False;ex=hb[-1][2];why='close'
            for h,l,c in hb:
                if not started:
                    if (side=='L' and h>hi) or (side=='S' and l<lo): started=True
                    continue
                if side=='L' and l<=stop: ex=stop;why='stop';break
                if side=='S' and h>=stop: ex=stop;why='stop';break
            r=(ex/entry-1) if side=='L' else (entry/ex-1)
            w.writerow([d.isoformat(),s,side,entry,ex,why,round((r-0.0012)*100,4)]); print(d,s,side,f'{(r-0.0012)*100:+.2f}%',why)
print('완료',days[0],'~',days[-1])
