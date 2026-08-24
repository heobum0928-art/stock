"""Exit-rule engine.

One pass per (signal, intrabar-ordering) records config-independent events:
  - first crossing of each candidate ADVERSE price level (for a 2x short: price UP = adverse)
  - the trailing-stop exit event (trigger 15%p favorable, giveback 10%p) -- config independent
  - expiry (48h) close
Then any exit config is evaluated in O(1) from those events.

Justification for O(1): all trigger PRICES are config-independent; the trailing level
always lies BELOW entry price while every stop level lies ABOVE it, so within any
up-leg the trailing exit is always reached first.  Liquidation level (42.86% adverse
at mmr=5%) is above every stop level, so it can only fire on a gap.
"""
import numpy as np

MS = 300000
HOLD_BARS = 576           # 48h
TRAIL_TRIG = 15.0
TRAIL_GIVE = 10.0
LEV = 2.0
FEE_SIDE = 0.0006         # 0.04% fee + 0.02% slippage, per side, on NOTIONAL
STOP_EXTRA = 0.0005       # additional slippage on triggered (stop-type) exits
MMR = 0.05

def liq_adverse_pct(mmr=MMR):
    return (1 - LEV*mmr) / (LEV*(1+mmr)) * 100   # 42.857 at mmr=5%

LEVELS = [8.0, 12.0, 16.0, 20.0, 25.0, 30.0, 40.0, liq_adverse_pct()]

def scan(h, l, o, c, P0, opt=True, levels=LEVELS):
    """Returns (found, trail_ev, expiry_ev, mae_pct, mfe_pct).
    found[k] = (order, bar, fillprice) or None, for levels[k].
    order = global monotone int; expiry order = +inf sentinel."""
    n = len(c)
    nl = len(levels)
    lvlp = [P0*(1+x/100) for x in levels]
    found = [None]*nl
    lo_i = 0                      # index of lowest not-yet-found level
    trail_ev = None
    peak_fav = 0.0
    mae = 0.0
    order = 0
    prev = P0                     # carry across bars: the gap from the last close
    for i in range(n):
        oi = o[i]; hi = h[i]; li = l[i]; ci = c[i]
        a = (hi/P0-1)*100
        if a > mae: mae = a
        path = (oi, li, hi, ci) if opt else (oi, hi, li, ci)
        for k in range(4):
            nxt = path[k]
            if nxt > prev:
                # trailing first (its price is below P0, all stop levels are above P0)
                if trail_ev is None and peak_fav >= TRAIL_TRIG:
                    tl = P0*(1-(peak_fav-TRAIL_GIVE)/100)
                    if tl <= prev:
                        trail_ev = (order, i, prev)
                    elif tl <= nxt:
                        trail_ev = (order, i, nxt if k == 0 else tl)
                gap = (k == 0)   # prev close -> this open: no trading in between
                j = lo_i
                while j < nl:
                    if found[j] is None:
                        lp = lvlp[j]
                        if lp <= prev:
                            found[j] = (order, i, prev)
                        elif lp <= nxt:
                            found[j] = (order, i, nxt if gap else lp)
                        else:
                            break
                    j += 1
                while lo_i < nl and found[lo_i] is not None:
                    lo_i += 1
            else:
                f = (1-nxt/P0)*100
                if f > peak_fav: peak_fav = f
            prev = nxt
            order += 1
        # early exit: if trail found and top level found nothing more can change
        if trail_ev is not None and lo_i >= nl:
            break
    expiry = (10**9, n-1, c[n-1])
    return found, trail_ev, expiry, mae, peak_fav


class SigEvents:
    __slots__=("found","trail","expiry","mae","mfe","P0","t0","bt","levels","nbars","cumfund")
    def __init__(self, found, trail, expiry, mae, mfe, P0, t0, bt, nbars):
        self.found=found; self.trail=trail; self.expiry=expiry
        self.mae=mae; self.mfe=mfe; self.P0=P0; self.t0=t0; self.bt=bt; self.nbars=nbars
        self.cumfund=None

LIQ_IDX = len(LEVELS)-1
IDX = {v:i for i,v in enumerate(LEVELS)}

def _ev(se, lvl):
    e = se.found[IDX[lvl]]
    return e

def evaluate(se, T1, R, Seff, F, extra_fill_cost=0.0, funding_fn=None):
    """T1: stage-1 adverse trigger (None if single-stop rule); R: fraction closed at T1;
    Seff: adverse stop for the remainder after stage 1; F: full-exit adverse line.
    Returns dict."""
    liq = _ev(se, LEVELS[LIQ_IDX])
    eF = _ev(se, F)
    tr = se.trail
    exp = se.expiry
    BIG = 10**9

    def key(e):
        # (leg order, fill price): within one up-leg prices are hit in ascending order,
        # so price is the correct tie-break (trailing level < P0 < every stop level).
        return (BIG+1, 0.0) if e is None else (e[0], e[2])

    fills = []
    liq_flag = False
    cands = [(key(eF), eF, 'stop'), (key(tr), tr, 'trail'),
             (key(liq), liq, 'liq'), (key(exp), exp, 'expiry')]
    cands.sort(key=lambda x: x[0])
    first_full = cands[0]

    e1 = _ev(se, T1) if (T1 is not None and R > 0) else None
    if e1 is not None and key(e1) < first_full[0]:
        fills.append((R, e1[2], 'stop', e1[1]))
        q = 1.0 - R
        eS = _ev(se, Seff)
        c2 = [(key(eS), eS, 'stop'), (key(tr), tr, 'trail'),
              (key(liq), liq, 'liq'), (key(exp), exp, 'expiry')]
        c2 = [x for x in c2 if x[0] > key(e1)]
        c2.sort(key=lambda x: x[0])
        fin = c2[0]
        fills.append((q, fin[1][2], fin[2], fin[1][1]))
    else:
        fin = first_full
        fills.append((1.0, fin[1][2], fin[2], fin[1][1]))
    if fin[2] == 'liq':
        liq_flag = True

    P0 = se.P0
    tot = -LEV*FEE_SIDE                      # entry cost
    for (w, P, kind, bi) in fills:
        tot += -LEV*w*(P/P0 - 1)
        tot -= LEV*w*FEE_SIDE
        if kind != 'expiry':
            tot -= LEV*w*STOP_EXTRA
    if len(fills) > 1:
        tot -= extra_fill_cost*(len(fills)-1)
    if funding_fn is not None:
        tot += funding_fn(se, fills)
    _liqp = P0*(1+LEVELS[LIQ_IDX]/100)
    if any(P >= _liqp for (_w, P, _k, _b) in fills):
        liq_flag = True
    if liq_flag:
        tot = -1.0
    if tot < -1.0:
        # isolated margin cannot lose more than 100%: funding/fee drain would have
        # triggered liquidation first.
        tot = -1.0; liq_flag = True
    exit_bar = fills[-1][3]
    return {"ret": tot, "liq": liq_flag, "exit_bar": exit_bar,
            "exit_ts": int(se.bt[exit_bar]) if exit_bar < len(se.bt) else int(se.bt[-1]),
            "nfills": len(fills), "kind": fills[-1][2],
            "staged": len(fills) > 1}


def funding(se, fills):
    """Short receives funding when the rate is positive. cumfund is the cumulative
    funding rate from entry to each bar; multiply by leverage and the fraction held."""
    if se.cumfund is None: return 0.0
    tot = 0.0; q = 1.0; prev = 0.0
    for (w, P, kind, bi) in fills:
        cf = float(se.cumfund[bi])
        tot += LEV*q*(cf - prev)
        prev = cf; q -= w
    return tot
