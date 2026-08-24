"""업비트 원화 5분봉 스냅샷 1,374개를 종목별 단일 시계열로 병합."""
import json, glob, os, re, sys
import numpy as np
from collections import defaultdict
SRC='data/candles_cache'; OUT='research/upbit5m/pq'
os.makedirs(OUT, exist_ok=True)
files=glob.glob(os.path.join(SRC,'*_5m_90d_*.json'))
by=defaultdict(list)
for p in files:
    m=re.match(r'(.+?)_5m_90d_\d{4}-\d{2}-\d{2}\.json$', os.path.basename(p))
    if m: by[m.group(1)].append(p)
print('코인 {}종, 파일 {}개'.format(len(by), len(files)), flush=True)
ok=0; skip=0
for i,(coin,ps) in enumerate(sorted(by.items())):
    rows={}
    for p in ps:
        try:
            for r in json.load(open(p, encoding='utf-8')):
                ts=r['timestamp']//300000*300000
                rows[ts]=(r['opening_price'],r['high_price'],r['low_price'],r['trade_price'],
                          r.get('candle_acc_trade_price',0.0),r.get('candle_acc_trade_volume',0.0))
        except Exception as e:
            print('ERR',p,e, flush=True)
    if len(rows)<2000: skip+=1; continue
    t=np.array(sorted(rows), dtype=np.int64)
    a=np.array([rows[x] for x in t], dtype=np.float64)
    np.savez_compressed(os.path.join(OUT, coin+'.npz'), t=t,
                        o=a[:,0],h=a[:,1],l=a[:,2],c=a[:,3],qv=a[:,4],v=a[:,5])
    ok+=1
    if (i+1)%25==0: print('{}/{}  {}  bars={}'.format(i+1,len(by),coin,len(t)), flush=True)
print('완료: 저장 {}종, 봉 부족으로 제외 {}종'.format(ok,skip), flush=True)
