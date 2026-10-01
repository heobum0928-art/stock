"""모의 전용 — BTC·ETH·SOL 200일 규칙 균등 1/3 (PREREG_TREND200_PORT.md). 주문 API 없음, 가격 조회만.
하루 1회 실행: 전일 종가로 신호 판단, 상태 변화 시 data/trend3_paper_trades.csv 기록."""
import json, os, csv, datetime as dt, requests
SYMS=('BTCUSDT','ETHUSDT','SOLUSDT'); CAP=1000.0
ST='data/trend3_paper_state.json'; TR='data/trend3_paper_trades.csv'
def closes(sym):
    r=requests.get('https://fapi.binance.com/fapi/v1/klines',params=dict(symbol=sym,interval='1d',limit=205),timeout=30).json()
    return [float(k[4]) for k in r[:-1]]   # 마지막(진행 중) 봉 제외
state=json.load(open(ST)) if os.path.exists(ST) else {s:{'on':0,'entry':None} for s in SYMS}
now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'); new=not os.path.exists(TR)
with open(TR,'a',newline='',encoding='utf-8') as f:
    w=csv.writer(f)
    if new: w.writerow(['time','symbol','action','price','ma200','pnl_pct_notional','pnl_usdt'])
    for s in SYMS:
        c=closes(s); px=c[-1]; ma=sum(c[-200:])/200; st=state[s]
        on=1 if px>ma*1.01 else (0 if px<ma*0.99 else st['on'])
        if on and not st['on']:
            w.writerow([now,s,'BUY',px,round(ma,4),'','']); st['entry']=px
        elif not on and st['on']:
            p=px/st['entry']-1-0.001; w.writerow([now,s,'SELL',px,round(ma,4),round(p*100,3),round(p*CAP/3,2)]); st['entry']=None
        st['on']=on; print(s,'ON' if on else 'OFF',px,round(ma,2))
json.dump(state,open(ST,'w'),indent=1)
