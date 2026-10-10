"""2배 병행 기록(가짜 돈·주문 없음): 5배 전환(2026-10-08 12:41 KST 설정 반영) 이후 완화봇 *선물* 진입 건을
'같은 진입·같은 청산인데 명목 160(2배·증거금 80)이었다면'으로 환산한다. 같은 거래의 손익은 명목에 비례하므로
2배 손익 = 실제(명목 400) 손익 × 160/400 = 0.4배(수수료·펀딩도 명목 비례). 원장(margin_short_wide_ledger.csv) 기준.
사용: python scripts/lev2_parallel.py  → data/lev2_parallel.csv 갱신 + 요약 출력."""
import pandas as pd,numpy as np
CUT=pd.Timestamp('2026-10-08 12:41:00',tz='Asia/Seoul')   # 5배 설정 반영 시각
K=160/400
w=pd.read_csv('data/margin_short_wide_ledger.csv')
w['t']=pd.to_datetime(w.entry_time,utc=True,format='mixed').dt.tz_convert('Asia/Seoul')
w['x']=pd.to_datetime(w.exit_time,utc=True,format='mixed').dt.tz_convert('Asia/Seoul')
d=w[(w.t>=CUT)&(w.reason.astype(str).str.contains(r'\[선물\]'))].sort_values('x').copy()
d['usd_5x']=d.net_pnl_usdt;d['usd_2x']=d.net_pnl_usdt*K
d['cum_5x']=d.usd_5x.cumsum();d['cum_2x']=d.usd_2x.cumsum()
out=d[['entry_time','exit_time','symbol','usd_5x','usd_2x','cum_5x','cum_2x']].round(2)
out.to_csv('data/lev2_parallel.csv',index=False,encoding='utf-8')
n=len(d)
if n==0: print('대상 건 없음'); raise SystemExit
day=d.x.dt.strftime('%m-%d')
g=d.groupby(day).agg(건수=('usd_5x','size'),usd_5x=('usd_5x','sum'),usd_2x=('usd_2x','sum')).round(1)
print(f'5배 전환 이후 완화봇 선물 {n}건 (이긴 {int((d.usd_5x>0).sum())} / 진 {int((d.usd_5x<=0).sum())})')
print(f'합계: 5배(실제) {d.usd_5x.sum():+.1f} USDT  |  2배였다면 {d.usd_2x.sum():+.1f} USDT  (차이 {d.usd_5x.sum()-d.usd_2x.sum():+.1f})')
print(f'최악 한 건: 5배 {d.usd_5x.min():+.1f} / 2배 {d.usd_2x.min():+.1f} | 최악의 날: 5배 {g.usd_5x.min():+.1f} / 2배 {g.usd_2x.min():+.1f}')
print('일별(5배 / 2배 환산):');print(g.to_string())
