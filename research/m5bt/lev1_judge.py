"""PREREG_LEV1.md 판정 — 기준은 2026-08-24에 확정됨. 변경 금지."""
import numpy as np, datetime as dt
a=np.load('lev1.npy')
A,B=a['A']*100,a['B']*100
d=B-A
print('=== 기본 ===')
print('  n={}  A(현행 2배/-40%) {:+.3f}%   B(1배/-80%) {:+.3f}%'.format(len(a),A.mean(),B.mean()))
print('  짝차이 B-A = {:+.3f}%p   (짝차이 SD {:.2f}, SE {:.3f})'.format(d.mean(),d.std(ddof=1),d.std(ddof=1)/np.sqrt(len(d))))
print('  강제청산 A {}건({:.1f}%) / B {}건({:.1f}%)'.format(a['liqA'].sum(),100*a['liqA'].mean(),a['liqB'].sum(),100*a['liqB'].mean()))
print('  승률 A {:.1f}% / B {:.1f}%'.format(100*(A>0).mean(),100*(B>0).mean()))
print()
print('=== 1차 관문 (4개 전부 충족해야 개선) ===')
print('1) 짝차이 > 0 : {:+.3f}%p -> {}'.format(d.mean(),'OK' if d.mean()>0 else 'FAIL'))
rng=np.random.default_rng(20260824); us=np.unique(a['sym']); idx={s:np.flatnonzero(a['sym']==s) for s in us}
bs=np.array([d[np.concatenate([idx[us[p]] for p in rng.integers(0,len(us),len(us))])].mean() for _ in range(4000)])
lo,hi=np.percentile(bs,[2.5,97.5])
print('2) 부트스트랩 95% CI [{:+.3f}, {:+.3f}] -> {}'.format(lo,hi,'OK(0 제외)' if (lo>0 or hi<0) else 'FAIL(0 포함)'))
h=a['hold']; dh=d[h].mean()
print('3) 홀드아웃 짝차이 {:+.3f}%p (n={}) -> {}'.format(dh,h.sum(),'OK(부호동일)' if np.sign(dh)==np.sign(d.mean()) else 'FAIL(부호반전)'))
day=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m-%d') for x in a['t0']])
ex=day!='2025-10-11'; de=d[ex].mean()
print('4) 2025-10-11 제외 {:+.3f}%p (제외 {}건) -> {}'.format(de,(~ex).sum(),'OK(부호동일)' if np.sign(de)==np.sign(d.mean()) else 'FAIL(부호반전)'))
print()
print('=== 2차 관문 (전략이 살아나는가) ===')
bsB=np.array([B[np.concatenate([idx[us[p]] for p in rng.integers(0,len(us),len(us))])].mean() for _ in range(4000)])
lb,hb=np.percentile(bsB,[2.5,97.5])
print('B 자체 기대값 {:+.3f}%  CI [{:+.3f}, {:+.3f}] -> {}'.format(B.mean(),lb,hb,'OK(>0 이고 CI 0제외)' if B.mean()>0 and lb>0 else 'FAIL'))
print()
print('=== 병기 ===')
mo=np.array([dt.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in a['t0']])
print('  월별 짝차이 (양수면 B우세)')
for m in sorted(set(mo)):
    s=mo==m
    print('    {}  n={:4d}  A {:+7.2f}%  B {:+7.2f}%  차이 {:+6.2f}%p'.format(m,s.sum(),A[s].mean(),B[s].mean(),d[s].mean()))
print()
print('  손절 발동 A {:.1f}% / B {:.1f}%'.format(100*a['stopA'].mean(),100*a['stopB'].mean()))
print('  ※ B는 같은 증거금으로 노출이 절반 — 자본 대비 총수익은 별도 해석 필요(사전등록 4절)')
