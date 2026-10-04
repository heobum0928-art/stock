"""prereg #43 PREREG_DELIST_BLOCK_CHECK.md"""
import pickle,json,sys,numpy as np
sys.path.insert(0,'.')
from bithumb.delist_guard import _tokens
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/'
ann={}
for x in json.load(open(S+'delist.json')):
    for t in _tokens(x['title']): ann.setdefault(t,[]).append(x['releaseDate'])
d=pickle.load(open('research/m5bt/wide_rows.pkl','rb'))['a']
sym=[str(s) for s in d['sym']];t0=np.asarray(d['t0'],dtype=np.int64);net=np.asarray(d['net'],dtype=float)/100.0
blk=np.zeros(len(d),bool);which=[]
for i,(s,t) in enumerate(zip(sym,t0)):
    base=s[:-4] if s.endswith('USDT') else s
    for a in ann.get(base,[]):
        if 0<=t-a<=30*86400000: blk[i]=True;which.append((base,int((t-a)/86400000)));break
print(f'신호 {len(d)}건 / 차단 대상 {blk.sum()}건 (코인 {len(set(w[0] for w in which))}종)')
if blk.sum()>0:
    print(f'차단 대상: 평균 {net[blk].mean()*100:+.2f}% 승률 {(net[blk]>0).mean()*100:.0f}% 최악 {net[blk].min()*100:+.0f}% | 나머지: 평균 {net[~blk].mean()*100:+.2f}% 승률 {(net[~blk]>0).mean()*100:.0f}%')
    print('코인(공지 후 며칠):',sorted(set(which))[:20])
    day=t0//86400000;days=np.unique(day);idx={dd:np.nonzero(day==dd)[0] for dd in days};rng=np.random.default_rng(20261004);ds=[]
    for _ in range(4000):
        sel=np.concatenate([idx[days[q]] for q in rng.integers(0,len(days),len(days))])
        a=net[sel][blk[sel]];b=net[sel][~blk[sel]]
        if len(a) and len(b): ds.append(a.mean()-b.mean())
    lo,hi=np.percentile(ds,[2.5,97.5]);df=net[blk].mean()-net[~blk].mean()
    print(f'차이(차단 대상 − 나머지) {df*100:+.2f}%p  95% CI [{lo*100:+.2f},{hi*100:+.2f}]')
    print(f'전체 평균 {net.mean()*100:+.3f}% → 차단 대상 제외 {net[~blk].mean()*100:+.3f}%')
    print('판정:','판별 불가(20건 미만)' if blk.sum()<20 else ('성립(차단 효과 확인)' if df<0 and hi<0 else '기각'))
else: print('판정: 판별 불가(차단 대상 0건)')
# 기술(판정 아님): 공지 후 경과일 구간별
age=np.full(len(d),np.nan)
for i,(s,t) in enumerate(zip(sym,t0)):
    base=s[:-4] if s.endswith('USDT') else s
    for a in ann.get(base,[]):
        if 0<=t-a<=30*86400000: age[i]=(t-a)/86400000;break
for lo_,hi_ in ((0,3),(3,14),(14,30.01)):
    m=(age>=lo_)&(age<hi_)
    if m.sum(): print(f'  공지 후 {lo_:.0f}~{hi_:.0f}일: n={m.sum()} 평균 {net[m].mean()*100:+.2f}% 승률 {(net[m]>0).mean()*100:.0f}% 중앙 {np.median(net[m])*100:+.1f}% 최악 {net[m].min()*100:+.0f}% (-50% 이하 {(net[m]<=-0.5).sum()}건)')
print(f'  나머지: -50% 이하 {(net[~blk]<=-0.5).sum()}건/{(~blk).sum()}  차단 대상: {(net[blk]<=-0.5).sum()}건/{blk.sum()}')
