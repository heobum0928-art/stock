"""고래 체결 후 가격 반응 — 기술적 측정만. 전략 검정 아님.
ChatGPT 권고: 방향 베팅을 붙이기 전에 "평상시 대비 무엇이 달라지는가"만 본다.
"""
import sys,os,glob; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, lib
w=pd.read_csv('data/whale_print_events.csv',on_bad_lines='skip')
w['time']=pd.to_datetime(w['time'],errors='coerce'); w=w.dropna(subset=['time'])
w['ts']=(w['time'].astype('int64')//10**6)          # KST 그대로(업비트 봉도 동일 기준)
have=set(lib.symbols())
w=w[w['coin'].isin(have)]
print('겹치는 종목 {}개, 이벤트 {:,}건'.format(w['coin'].nunique(),len(w)))
HZ={'15m':3,'1h':12,'4h':48,'24h':288}
res={k:{'sig':[],'base':[]} for k in HZ}
side={k:{'bid':[],'ask':[]} for k in HZ}
for coin,g in w.groupby('coin'):
    d=lib.load(coin); t=d['t']; c=d['c'].astype(float)
    n=len(t)
    idx=np.searchsorted(t,g['ts'].values)
    ok=(idx>0)&(idx<n-300)
    idx=idx[ok]; sd=g['side'].values[ok]; rt=g['ratio_to_median'].values[ok]
    big=rt>=230.2          # 상위 10% 크기만
    idx=idx[big]; sd=sd[big]
    if len(idx)<5: continue
    # 기준선: 같은 종목의 무작위 시점
    rng=np.random.default_rng(20260824+len(coin))
    bidx=rng.integers(1,n-300,size=min(len(idx)*3,2000))
    for k,h in HZ.items():
        for src,store in ((idx,'sig'),(bidx,'base')):
            j=src+h
            v=(c[j]/c[src]-1.0)*100
            cont=(t[j]-t[src])==h*lib.BAR_MS
            res[k][store].append(v[cont])
        j=idx+h; cont=(t[j]-t[idx])==h*lib.BAR_MS
        v=(c[j]/c[idx]-1.0)*100
        side[k]['bid'].append(v[cont&(sd[:len(cont)]=='bid')])
        side[k]['ask'].append(v[cont&(sd[:len(cont)]=='ask')])
print()
print('=== 고래 체결(크기 상위 10%) 후 가격 — 방향 ===')
print('{:>6} {:>9} {:>10} {:>10} {:>10}'.format('지평','n','고래후 평균%','무작위 평균%','차이%p'))
for k in HZ:
    s=np.concatenate(res[k]['sig']); b=np.concatenate(res[k]['base'])
    print('{:>6} {:>9,} {:>10.3f} {:>12.3f} {:>10.3f}'.format(k,len(s),s.mean(),b.mean(),s.mean()-b.mean()))
print()
print('=== 변동성(절대 수익률) — 고래가 큰 움직임을 예고하나 ===')
print('{:>6} {:>12} {:>12} {:>8}'.format('지평','고래후 |수익|','무작위 |수익|','배수'))
for k in HZ:
    s=np.abs(np.concatenate(res[k]['sig'])); b=np.abs(np.concatenate(res[k]['base']))
    print('{:>6} {:>12.3f} {:>12.3f} {:>8.2f}x'.format(k,s.mean(),b.mean(),s.mean()/max(b.mean(),1e-9)))
print()
print('=== 매수 고래 vs 매도 고래 ===')
print('{:>6} {:>10} {:>10} {:>10}'.format('지평','매수후 %','매도후 %','차이%p'))
for k in HZ:
    bi=np.concatenate(side[k]['bid']); ak=np.concatenate(side[k]['ask'])
    print('{:>6} {:>10.3f} {:>10.3f} {:>10.3f}'.format(k,bi.mean(),ak.mean(),bi.mean()-ak.mean()))
