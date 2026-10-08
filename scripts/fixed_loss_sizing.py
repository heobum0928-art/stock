"""기술(판정 아님): '한 건 손실 10달러 고정'일 때 손절폭별 건당 기대 달러 — 레버리지가 아니라 (명목 크기, 손절 %)가 결정.
research/m5bt scalpout.sim 재사용(손절 우선·STOP_EXTRA·펀딩 포함, 5분봉 경로)."""
import os,sys,pickle,numpy as np
M='research/m5bt';sys.path.insert(0,M)
import engine as E, build as B
import scalpout as SC
d=pickle.load(open(f'{M}/wide_rows.pkl','rb'));a,sc=d['a'],np.asarray(d['sc'],dtype=float)
STOPS=[5.0,2.5,1.7,1.0]            # 명목 손절 %. 명목 크기 N = 10/(S/100): 200, 400, 600, 1000 USDT
res={s:[] for s in STOPS};cache={};meta=[]
for n_,(sym,t0) in enumerate(zip(a['sym'],a['t0'])):
    sym=str(sym)
    if sym not in cache:
        z=np.load(os.path.join(M,'pq',sym+'.npz'));cache={sym:tuple(z[k] for k in ('t','o','h','l','c'))}
    t,o,h,l,c=cache[sym];i=int(np.searchsorted(t,t0))
    if i>=len(t) or int(t[i])!=int(t0): continue
    P0=float(c[i]);j=min(i+1+E.HOLD_BARS,len(c))
    if j-(i+1)<12: continue
    sl=slice(i+1,j);cf=B.cumfund_for(sym,int(t[i]),t[sl])
    for s in STOPS: res[s].append(SC.sim(P0,o[sl],h[sl],l[sl],c[sl],cf,s,None))
    meta.append(n_)
meta=np.array(meta);S_=sc[meta];print(f'시뮬 {len(meta)}건 (E.LEV={E.LEV}, 반환값은 증거금 기준 → 명목 = 값/LEV)')
for nm,mask in (('전체 신호',np.ones(len(meta),bool)),('CUSUM≥38.1(실거래 필터)',S_>=38.1)):
    print(f'\n[{nm}] n={mask.sum()}')
    for s in STOPS:
        net=np.array([r[0] for r in res[s]])[mask]/E.LEV      # 명목 수익률
        stopped=np.mean([r[1]=='stop' for r in np.array(res[s],dtype=object)[mask]])
        N=10/(s/100)
        print(f'  손절 명목 {s:>4}% | 명목 크기 {N:>5.0f} USDT(≈{N/E.LEV:.0f}증거금@2배, {N/5:.0f}@5배, {N/10:.0f}@10배) | 손절 비율 {stopped*100:3.0f}% | 건당 평균 명목 {net.mean()*100:+.3f}% → 건당 {net.mean()*N:+.2f} USDT | 하루 5건이면 {net.mean()*N*5:+.1f} USDT')

# ── 추가(기술): 손절 2.5%·명목 400 vs 현재 5%·명목 200 짝비교(CUSUM≥38.1), 날짜 클러스터 부트스트랩, 전/후반
m=S_>=38.1
n5=np.array([r[0] for r in res[5.0]])[m]/E.LEV*200;n25=np.array([r[0] for r in res[2.5]])[m]/E.LEV*400
t0m=np.asarray(a['t0'],dtype=np.int64)[meta][m];day=t0m//86400000;diff=n25-n5
days=np.unique(day);idx={x:np.nonzero(day==x)[0] for x in days};rng=np.random.default_rng(20261008);ms=[]
for _ in range(4000):
    sel=np.concatenate([idx[days[q]] for q in rng.integers(0,len(days),len(days))]);ms.append(diff[sel].mean())
lo,hi=np.percentile(ms,[2.5,97.5]);print(f"\n짝비교(2.5%·명목400 − 5%·명목200) 건당 {diff.mean():+.2f} USDT  95% CI [{lo:+.2f},{hi:+.2f}]  (n={m.sum()})")
med=np.median(day)
for nm,h in (('전반',day<=med),('후반',day>med)):
    print(f"  {nm}: 5% 건당 {n5[h].mean():+.2f} / 2.5% 건당 {n25[h].mean():+.2f} USDT (n={h.sum()})")
print(f"  손절 2.5% 최악 한 건 {n25.min():.1f} USDT(고정 -10 + 갭), 5% 최악 {n5.min():.1f}")

# ── 추가(기술, 사용자 관찰 "진입하면 대부분 +로 나온다"): 손절 5% 경로 기준 진입 후 1h·4h 시점 상태, 그리고 먼저 이익 쪽으로 간 비율
import numpy as np
cnt=0;early1=[];early4=[];mfe_first=[];final=[]
cache={}
for n_,(sym,t0) in enumerate(zip(a['sym'],a['t0'])):
    if n_ not in set(meta[m_idx] for m_idx in np.nonzero(S_>=38.1)[0]): continue
    sym=str(sym)
    if sym not in cache:
        z=np.load(os.path.join(M,'pq',sym+'.npz'));cache={sym:tuple(z[k] for k in ('t','o','h','l','c'))}
    t,o,h,l,c=cache[sym];i=int(np.searchsorted(t,t0))
    if i>=len(t) or int(t[i])!=int(t0) or i+1+E.HOLD_BARS>len(c): continue
    P0=float(c[i]);hh=h[i+1:i+1+E.HOLD_BARS];ll=l[i+1:i+1+E.HOLD_BARS];cc=c[i+1:i+1+E.HOLD_BARS]
    early1.append(1-cc[11]/P0);early4.append(1-cc[47]/P0)          # 숏 기준 이익(+) — 12봉=1h, 48봉=4h 시점 종가
    first_loss=np.argmax(hh>=P0*1.025) if (hh>=P0*1.025).any() else None
    first_gain=np.argmax(ll<=P0*0.975) if (ll<=P0*0.975).any() else None
    mfe_first.append((first_gain is not None) and (first_loss is None or first_gain<first_loss))
early1=np.array(early1);early4=np.array(early4)
print(f"\nCUSUM≥38.1 {len(early1)}건: 진입 1시간 뒤 이익 중 {np.mean(early1>0)*100:.0f}% (평균 {early1.mean()*100:+.2f}%) | 4시간 뒤 이익 중 {np.mean(early4>0)*100:.0f}% (평균 {early4.mean()*100:+.2f}%) | 손절 2.5%보다 이익 2.5%에 먼저 닿은 비율 {np.mean(mfe_first)*100:.0f}%")
