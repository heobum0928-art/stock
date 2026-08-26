"""PREREG_DD_SPEED.md 실행 — 역행 '속도'가 생존을 가르는가.
검증된 엔진 사용. 확장 레벨로 -20%/-40% 도달 시점을 얻는다."""
import os, glob
import numpy as np
import engine as E, signals as S, build as BU

D = os.path.dirname(os.path.abspath(__file__)); PQ = os.path.join(D, 'pq'); HOLD = 576
LIQ = (1 - 2.0*E.MMR) / (2.0*(1+E.MMR)) * 100
L20, L40 = 10.0, 20.0          # 명목 % → 증거금 20% / 40%
LEVELS = sorted(set([L20, L40, 8., 12., 16., 25., 30., 40.])) + [LIQ]
E.LEVELS = LEVELS; E.IDX = {v: i for i, v in enumerate(LEVELS)}; E.LIQ_IDX = len(LEVELS)-1

rows = []
for n_, p in enumerate(sorted(glob.glob(os.path.join(PQ, '*.npz')))):
    s = os.path.basename(p)[:-4]
    try: sg, arr = S.sigs_for(s)
    except Exception: continue
    if not sg: continue
    t, o, h, l, c, qv = arr
    for (i, ts, px0, ret7, v24) in sg:
        P0 = float(c[i]); j = min(i+1+HOLD, len(c))
        if j-(i+1) < 12: continue
        sl = slice(i+1, j); hh, ll, oo, cc, bt = h[sl], l[sl], o[sl], c[sl], t[sl]
        cf = BU.cumfund_for(s, int(t[i]), bt).astype(np.float32)
        f, tr, ex, mae, mfe = E.scan(hh, ll, oo, cc, P0, opt=True, levels=LEVELS)
        se = E.SigEvents(f, tr, ex, mae, mfe, P0, int(t[i]), bt, len(cc)); se.cumfund = cf
        r = E.evaluate(se, None, 0.0, 40.0, 40.0, funding_fn=E.funding)
        xb = r['exit_bar']
        e20 = f[E.IDX[L20]]; e40 = f[E.IDX[L40]]
        if e20 is None or e20[1] > xb:      # -20% 안 밟았으면 대상 아님
            continue
        b20 = int(e20[1])
        # 특징1: -20% -> -40% 소요(분). -40% 미도달이면 검열
        if e40 is not None and e40[1] <= xb:
            gap = (int(e40[1]) - b20) * 5.0
            cens = 0
        else:
            gap = np.nan; cens = 1
        # 특징2: -20% 도달 후 1시간(12봉) 추가 역행 %p (증거금 기준)
        b1 = min(b20+12, len(cc)-1)
        add1h = (hh[b20:b1+1].max()/P0 - 1)*100*2 - 20.0 if b1 >= b20 else np.nan
        # 특징3: 가속도 = (진입->-20% 소요) / (-20%->-40% 소요)
        to20 = (b20+1)*5.0
        accel = to20/gap if (gap and np.isfinite(gap) and gap > 0) else np.nan
        rows.append((s, int(ts), bool(BU.holdout(s)), r['ret']*100, gap, cens, add1h, accel, to20))
    if (n_+1) % 200 == 0: print('  {}/805 {}'.format(n_+1, len(rows)), flush=True)

dt = [('sym','U15'),('t0','i8'),('hold','?'),('ret','f8'),
      ('gap','f8'),('cens','i1'),('add1h','f8'),('accel','f8'),('to20','f8')]
a = np.array(rows, dtype=dt)
np.save(os.path.join(D, 'ddspeed.npy'), a)
print('-20% 도달 {}건 (검열 {}건)'.format(len(a), int(a['cens'].sum())), flush=True)
