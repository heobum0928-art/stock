"""단기 급등 페이드(spike short) 1년 검증 — 빗썸 5일치에서 나온 가설을 바이낸스 1년으로.

가설 출처: data/spike_outcomes.csv (2026-06-30~07-05, 빗썸 29종목 948건).
거래량 급증 시점에 "이미 많이 오른" 상위25%(+8% 이상) 신호를 숏치고 60분 보유하면
평균 +1.15%(코인블록 95%CI [+0.46,+2.75], 5일 모두 양수). 단 5일·13코인·다른 거래소라
결론 불가 → 바이낸스 805종목 1년으로 재검증한다.

★ 규칙은 결과 보기 전에 고정한다(격자 스캔 금지, CLAUDE.md 5항).
  진입: 직전 30분(6봉) 상승률 >= 8.0% AND 해당 봉 거래대금 >= 직전 24h 봉중앙값 × 10
        → 그 봉 종가에 숏
  청산: 60분(12봉) 뒤 종가 (손절·트레일링 없음 — 원가설 그대로)
  쿨다운: 코인당 12봉(60분)
  비용: 왕복 수수료 0.12% + 슬리피지 0.05% 차감
  잣대: 명목 기준 % (증거금 기준은 레버리지 배수만큼 곱하면 됨)
"""
import os, glob, hashlib
import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
PQ = os.path.join(D, "pq")

PUMP_BARS = 6        # 30분
PUMP_PCT = 8.0
VOL_MULT = 10.0
VOL_WIN = 288        # 24h 중앙값
HOLD_BARS = 12       # 60분
COOLDOWN = 12
COST_PCT = 0.17      # 왕복 수수료 0.12 + 슬리피지 0.05


def holdout(sym):
    return int(hashlib.md5(sym.encode()).hexdigest(), 16) % 4 == 0


def scan_symbol(sym):
    z = np.load(os.path.join(PQ, sym + ".npz"))
    t, c, qv = z["t"], z["c"], z["qv"]
    n = len(c)
    if n < VOL_WIN + HOLD_BARS + PUMP_BARS + 10:
        return []
    ret = np.full(n, np.nan)
    ret[PUMP_BARS:] = (c[PUMP_BARS:] / c[:-PUMP_BARS] - 1) * 100
    out = []
    last = -10**9
    # 거래량 중앙값은 롤링이라 무겁다 — 24h 창을 288봉 단위로 미리 계산해 근사(창 시작점 고정)
    for i in range(VOL_WIN, n - HOLD_BARS - 1):
        if i - last < COOLDOWN:
            continue
        if np.isnan(ret[i]) or ret[i] < PUMP_PCT:
            continue
        med = np.median(qv[i - VOL_WIN:i])
        if med <= 0 or qv[i] < med * VOL_MULT:
            continue
        entry = float(c[i]); exitp = float(c[i + HOLD_BARS])
        pnl = (1 - exitp / entry) * 100 - COST_PCT      # 숏: 가격 하락이 이익
        out.append((sym, int(t[i]), float(ret[i]), pnl))
        last = i
    return out


if __name__ == "__main__":
    syms = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ, "*.npz")))
    recs = []
    for si, s in enumerate(syms):
        try:
            recs.extend(scan_symbol(s))
        except Exception:
            pass
        if (si + 1) % 200 == 0:
            print(f"  {si+1}/{len(syms)} 신호 {len(recs)}건", flush=True)

    if not recs:
        print("신호 0건 — 문턱이 너무 빡빡함(규칙은 고정이므로 조정하지 않고 그대로 보고)")
        raise SystemExit

    pnl = np.array([r[3] for r in recs])
    sym_arr = np.array([r[0] for r in recs])
    ts = np.array([r[1] for r in recs])
    hold = np.array([holdout(s) for s in sym_arr])
    n = len(pnl)

    rs = np.random.RandomState(20260901); B = 4000
    u = np.unique(sym_arr); idx = {k: np.nonzero(sym_arr == k)[0] for k in u}
    boot = np.array([pnl[np.concatenate([idx[u[i]] for i in rs.randint(0, len(u), len(u))])].mean()
                     for _ in range(B)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    big = np.argmax(np.abs(pnl - pnl.mean()))

    print(f"\n=== 단기 급등 페이드 (30분 +8% & 거래량 10배 → 숏 60분) ===")
    print(f"신호 {n}건 / {len(u)}종목 (비용 {COST_PCT}% 차감 후, 명목 기준)")
    print(f"평균 {pnl.mean():+.3f}%  중앙값 {np.median(pnl):+.3f}%  승률 {(pnl>0).mean()*100:.1f}%")
    print(f"심볼블록 부트스트랩 95%CI [{lo:+.3f}, {hi:+.3f}]  {'0 배제' if lo>0 or hi<0 else '0 포함'}")
    print(f"훈련 {pnl[~hold].mean():+.3f}%  홀드아웃 {pnl[hold].mean():+.3f}%  "
          f"{'부호일치' if (pnl[hold].mean()>0)==(pnl[~hold].mean()>0) else '★부호불일치'}")
    print(f"최대기여 1건({sym_arr[big]}, {pnl[big]:+.1f}%) 제외 {np.delete(pnl, big).mean():+.3f}%")
    print(f"최악10 평균 {np.sort(pnl)[:10].mean():+.2f}%  최대손실 {pnl.min():+.2f}%")

    import datetime
    months = np.array([datetime.datetime.utcfromtimestamp(x/1000).strftime('%Y-%m') for x in ts])
    print("\n월별(단일 사건 집중 확인):")
    for m in sorted(set(months)):
        a = pnl[months == m]
        print(f"  {m}: n={len(a):4d}  평균 {a.mean():+.3f}%")
