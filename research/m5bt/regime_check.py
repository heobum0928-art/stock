"""PREREG_REGIME_FILTER.md 실행."""
import numpy as np, datetime as dt, hashlib
from numpy.lib.stride_tricks import sliding_window_view
TH=3.26; W=288
z=np.load('pq/BTCUSDT.npz'); bt,bh,bl=z['t'],z['h'],z['l']; n=len(bt)
vol=np.full(n,np.nan)
vol[W-1:]=(sliding_window_view(bh,W).max(1)/sliding_window_view(bl,W).min(1)-1)*100
d=np.load('base_real.npz',allow_pickle=True)
sym,t0,ret,hold=d['sym'],d['t0'],d['ret_opt']*100,d['hold']
k=np.searchsorted(bt,t0,side='right')-1
k=np.clip(k,0,n-1); sv=vol[k]
ok=np.isfinite(sv)
turb=ok&(sv>TH); calm=ok&(sv<=TH)
mo=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in t0])
def desc(m,lab):
    r=ret[m]; print('  {:8s} n={:5d} ({:4.1f}%)  평균 {:+7.3f}%  승률 {:5.1f}%  SE {:.3f}  총손익 {:+9.1f}'.format(
        lab,len(r),100*len(r)/ok.sum(),r.mean(),100*(r>0).mean(),r.std(ddof=1)/np.sqrt(len(r)),r.sum()))
print('=== 전체 {}건 중 레짐 판정가능 {}건 ==='.format(len(ret),ok.sum()))
desc(calm,'평온장'); desc(turb,'변동장')
diff=ret[turb].mean()-ret[calm].mean()
print()
print('기준1  변동장 − 평온장 = {:+.3f}%p  -> {}'.format(diff,'변동장이 나쁨 ✓' if diff<0 else '★변동장이 오히려 나음 = 실패'))
# 기준2 종목 클러스터 부트스트랩
rng=np.random.default_rng(20260825); us=np.unique(sym); idx={s:np.flatnonzero(sym==s) for s in us}
bs=[]
for _ in range(4000):
    pick=rng.integers(0,len(us),len(us))
    ii=np.concatenate([idx[us[p]] for p in pick])
    a=turb[ii]; b=calm[ii]
    if a.sum()<10 or b.sum()<10: continue
    bs.append(ret[ii][a].mean()-ret[ii][b].mean())
bs=np.array(bs); lo,hi=np.percentile(bs,[2.5,97.5])
print('기준2  부트스트랩 95% CI [{:+.3f}, {:+.3f}]  -> {}'.format(lo,hi,'0 제외 ✓' if hi<0 or lo>0 else '★0 포함 = 실패'))
# 기준3 홀드아웃
dh=ret[turb&hold].mean()-ret[calm&hold].mean()
print('기준3  홀드아웃 차이 {:+.3f}%p (n={}/{})  -> {}'.format(dh,(turb&hold).sum(),(calm&hold).sum(),
      '부호 동일 ✓' if np.sign(dh)==np.sign(diff) else '★부호 반전 = 실패'))
# 기준4 2025-10 제외
ex=mo!='2025-10'
de=ret[turb&ex].mean()-ret[calm&ex].mean()
print('기준4  2025-10 제외 차이 {:+.3f}%p  -> {}'.format(de,'부호 유지 ✓' if np.sign(de)==np.sign(diff) else '★부호 반전 = 실패'))
# 기준5 월별
cnt=0; tot=0
for m in sorted(set(mo)):
    s=mo==m; a=turb&s; b=calm&s
    if a.sum()<5 or b.sum()<5: continue
    tot+=1
    if np.sign(ret[a].mean()-ret[b].mean())==np.sign(diff): cnt+=1
print('기준5  월별 부호일치 {}/{}  -> {}'.format(cnt,tot,'8개월 이상 ✓' if cnt>=8 else '★미달 = 실패'))
print()
print('[병기] 시간 43.4% 차단 vs 실제 신호 차단 비율 {:.1f}%'.format(100*turb.sum()/ok.sum()))
print('[병기] 필터 없음 총손익 {:+.1f}  /  필터 적용(평온장만) {:+.1f}  -> 차단으로 {:+.1f} 절약'.format(
    ret[ok].sum(), ret[calm].sum(), -ret[turb].sum()))
