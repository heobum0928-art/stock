"""완화봇(margin_short_wide_trader.py, 7h+15~30% 급등) 신호셋에도 V1_notrail(트레일링
제거)이 유효한지 확인. PREREG_V1_NOTRAIL.md는 원본봇 신호(7h+30~40%)만 검증했다 —
완화봇은 진입필터만 다르고 청산규칙(손절40%/트레일링15·10/48h)은 원본과 동일
(margin_short_wide_trader.py:94-160 확인). v1_bt.py와 동일한 방식(se.trail 토글)을
완화봇 신호셋에 그대로 적용한다. 2026-08-31 대화 중 요청."""
import os, glob, hashlib
import numpy as np
import engine as E
import signals as SIG

D = os.path.dirname(os.path.abspath(__file__))
PQ = os.path.join(D, "pq")
HOLD_BARS = 576

# 완화봇 필터로 교체 (margin_short_wide_trader.py 실측: PUMP_PCT=15.0, PUMP_PCT_MAX=30.0,
# MIN_QUOTE_VOL=3_000_000 — signals.py의 MIN_QV와 동일이라 그대로 둔다)
SIG.PUMP_LO, SIG.PUMP_HI = 15.0, 30.0


def holdout(sym):
    return int(hashlib.md5(sym.encode()).hexdigest(), 16) % 4 == 0


def cumfund_for(sym, t0, bt):
    p = os.path.join(D, "fund", sym + ".npz")
    if not os.path.exists(p):
        return np.zeros(len(bt), np.float64)
    z = np.load(p)
    ft = z[z.files[0]]; fr = z[z.files[1]]
    cs = np.concatenate(([0.0], np.cumsum(fr)))
    lo = np.searchsorted(ft, t0, side="right")
    hi = np.searchsorted(ft, bt, side="right")
    return cs[hi] - cs[lo]


if __name__ == "__main__":
    syms = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ, "*.npz")))
    rows = []
    for si, s in enumerate(syms):
        sg, arr = SIG.sigs_for(s)
        if not sg:
            continue
        t, o, h, l, c, qv = arr
        for (i, ts, px, ret7, v24) in sg:
            P0 = float(c[i]); j = min(i + 1 + HOLD_BARS, len(c))
            if j - (i + 1) < 12:
                continue
            sl = slice(i + 1, j)
            hh, ll, oo, cc, bt = h[sl], l[sl], o[sl], c[sl], t[sl]
            cf = cumfund_for(s, int(t[i]), bt)
            f, tr, ex, mae, mfe = E.scan(hh, ll, oo, cc, P0, opt=True)
            se = E.SigEvents(f, tr, ex, mae, mfe, P0, int(t[i]), bt, len(cc))
            se.cumfund = cf.astype(np.float32)
            r0 = E.evaluate(se, None, 0.0, 40.0, 40.0, funding_fn=E.funding)   # V0 (트레일링 있음)
            sv = se.trail; se.trail = None
            r1 = E.evaluate(se, None, 0.0, 40.0, 40.0, funding_fn=E.funding)   # V1 (트레일링 없음)
            se.trail = sv
            rows.append((s, int(ts), holdout(s), r0['ret']*100.0, r1['ret']*100.0, r0['kind']))
        if (si + 1) % 200 == 0:
            print(f"  {si+1}/{len(syms)} 종목, 신호 {len(rows)}건", flush=True)

    v0 = np.array([r[3] for r in rows])
    v1 = np.array([r[4] for r in rows])
    sym = np.array([r[0] for r in rows])
    hold = np.array([r[2] for r in rows], bool)
    kind0 = np.array([r[5] for r in rows])
    df = v1 - v0
    n = len(df)
    print(f"\n=== 완화봇 신호셋(7h+15~30%, n={n}): 트레일링 제거(V1) vs 현행(V0) ===")
    print(f"  V0 {v0.mean():+.2f}%   V1 {v1.mean():+.2f}%   짝차이 {df.mean():+.2f}%p")
    nz = df[df != 0]
    print(f"  차이 있는 쌍 {len(nz)}건  V1승 {(nz>0).sum()}  V0승 {(nz<0).sum()}")

    rng = np.random.RandomState(20260831)
    B = 4000
    u = np.unique(sym)
    idx = {k: np.nonzero(sym == k)[0] for k in u}
    boot = np.empty(B)
    for bi in range(B):
        pick = rng.randint(0, len(u), len(u))
        boot[bi] = df[np.concatenate([idx[u[k]] for k in pick])].mean()
    lo95, hi95 = np.percentile(boot, [2.5, 97.5])
    lo99, hi99 = np.percentile(boot, [0.5, 99.5])

    order = np.argsort(-np.abs(df))
    big = order[0]
    df_excl = np.delete(df, big)

    fired = df != 0
    fired_win = (df[fired] > 0).sum()

    print()
    print("[C1] 짝차이 평균 > 0            :", f"{df.mean():+.2f}%p", "통과" if df.mean() > 0 else "기각")
    print("[C2] 95% CI 하한 > 0            :", f"[{lo95:+.2f},{hi95:+.2f}]", "통과" if lo95 > 0 else "기각")
    print("[C3] 최대기여 제외 부호유지      :", f"{sym[big]} {df[big]:+.2f}%p 제외 → {df_excl.mean():+.2f}%p",
          "통과" if (df_excl.mean() > 0) == (df.mean() > 0) else "기각")
    print("[C4] 99% CI 하한 > 0            :", f"[{lo99:+.2f},{hi99:+.2f}]", "통과" if lo99 > 0 else "기각")
    print("[C5] 발동쌍 승률 > 50%          :", f"{fired_win}/{fired.sum()} ({fired_win/fired.sum()*100:.1f}%)" if fired.sum() else "발동 0건",
          "통과" if fired.sum() and fired_win/fired.sum() > 0.5 else "기각")
    dh = df[hold].mean()
    print("[참고] 홀드아웃 부호일치         :", f"훈련 {df[~hold].mean():+.2f}%p / 홀드아웃 {dh:+.2f}%p",
          "일치" if (dh > 0) == (df.mean() > 0) else "불일치")

    import pickle
    pickle.dump(rows, open(os.path.join(D, "wide_v1_result.pkl"), "wb"))
    print(f"\n완료: {n}건 → wide_v1_result.pkl")
