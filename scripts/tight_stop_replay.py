"""prereg #49 PREREG_TIGHT_STOP_REPLAY.md — 가짜 돈·주문 없음(공개 시세만).
완화봇 실제 진입 건을 손절 5%(명목200) vs 2.5%(명목400)로 같은 규칙 재생. 멱등: 이미 기록된 (entry_time,symbol)은 건너뜀.
인자 --backfill YYYY-MM-DD: 해당 날짜 이후 진입분을 'backfill' 표시로 기록(판정 제외, 검증용)."""
import sys,os,csv,time,datetime as dt,requests,pandas as pd,numpy as np
sys.path.insert(0,'research/m5bt')
import engine as E
OUT='data/tight_stop_replay.csv';KST=dt.timezone(dt.timedelta(hours=9))
START=dt.datetime(2026,10,9,tzinfo=KST)
bf=None
if len(sys.argv)>2 and sys.argv[1]=='--backfill': bf=dt.datetime.fromisoformat(sys.argv[2]).replace(tzinfo=KST);START=bf
tr=pd.read_csv('data/margin_short_wide_trades.csv');tr=tr[tr['live']==True].copy()
tr['t']=pd.to_datetime(tr.entry_time,format='mixed',utc=True).dt.tz_convert(KST)
tr=tr[tr.t>=START]
done=set()
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT,encoding='utf-8')): done.add((r['entry_time'],r['symbol']))
now=dt.datetime.now(KST);rows=[]
def sim(P0,hh,cc,stop):
    sl=P0*(1+stop/100);hit=np.nonzero(hh>=sl)[0]
    if len(hit): fill=sl;kind='stop'
    else: fill=float(cc[-1]);kind='expiry'
    nom=-(fill/P0-1)-2*E.FEE_SIDE-(E.STOP_EXTRA if kind=='stop' else 0.0)
    return nom,kind
for _,r in tr.iterrows():
    key=(r.entry_time,r.symbol)
    if key in done: continue
    if r.t+dt.timedelta(hours=48,minutes=10)>now: continue
    t0=int(r.t.timestamp()*1000)
    k=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol=r.symbol,interval='5m',startTime=t0,endTime=t0+48*3600*1000-1,limit=1000),timeout=30).json()
    if not isinstance(k,list) or len(k)<500: print('시세 부족',r.symbol,len(k) if isinstance(k,list) else k);continue
    hh=np.array([float(x[2]) for x in k]);cc=np.array([float(x[4]) for x in k]);P0=float(r.entry_price)
    nA,kA=sim(P0,hh,cc,5.0);nB,kB=sim(P0,hh,cc,2.5)
    rows.append([r.entry_time,r.symbol,P0,round(nA*100,4),kA,round(nA*200,3),round(nB*100,4),kB,round(nB*400,3),'backfill' if bf else 'live'])
    time.sleep(0.05)
new=not os.path.exists(OUT)
with open(OUT,'a',newline='',encoding='utf-8') as f:
    w=csv.writer(f)
    if new: w.writerow(['entry_time','symbol','entry_price','nomA_pct','kindA','usdA','nomB_pct','kindB','usdB','tag'])
    w.writerows(rows)
print('추가',len(rows),'건')
d=pd.read_csv(OUT);d=d[d.tag=='live'] if bf is None else d
print(f'누적 {len(d)}건 | A(5%·200) 건당 {d.usdA.mean():+.2f} 손절 {np.mean(d.kindA=="stop")*100:.0f}% | B(2.5%·400) 건당 {d.usdB.mean():+.2f} 손절 {np.mean(d.kindB=="stop")*100:.0f}%' if len(d) else '누적 0건')
