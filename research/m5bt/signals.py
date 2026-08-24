"""Generate entry signals under the CURRENT (frozen) entry rules.
7h return in [30,40)%, 24h quote vol >= 3M, 12h per-coin cooldown,
skip symbols younger than 30 days at signal time (bot routes those to paper-long).
Backtest window: 2025-08-01 .. 2026-07-31 (UTC).
"""
import os, json, glob
import numpy as np

D = os.path.dirname(os.path.abspath(__file__))
PQ = os.path.join(D, "pq")
LOOKBACK = 84          # 7h of 5m bars
VOLWIN = 288           # 24h
MIN_QV = 3_000_000
PUMP_LO, PUMP_HI = 30.0, 40.0
COOLDOWN_MS = 12*3600*1000
NEWLIST_MS = 30*24*3600*1000
WIN_S = 1754006400000  # 2025-08-01
WIN_E = 1785523200000  # 2026-08-01

def load(sym):
    z = np.load(os.path.join(PQ, sym + ".npz"))
    return z["t"], z["o"], z["h"], z["l"], z["c"], z["qv"]

def sigs_for(sym):
    t,o,h,l,c,qv = load(sym)
    n = len(t)
    if n < LOOKBACK + VOLWIN + 600:
        return None, (t,o,h,l,c,qv)
    # contiguity check: mark bars where t[i]-t[i-LOOKBACK] == LOOKBACK*300000
    ms = 300000
    ok_lb = np.zeros(n, bool)
    ok_lb[LOOKBACK:] = (t[LOOKBACK:] - t[:-LOOKBACK]) == LOOKBACK*ms
    ok_vw = np.zeros(n, bool)
    ok_vw[VOLWIN-1:] = (t[VOLWIN-1:] - t[:n-VOLWIN+1]) == (VOLWIN-1)*ms
    ret = np.full(n, np.nan)
    ret[LOOKBACK:] = (c[LOOKBACK:]/c[:-LOOKBACK] - 1)*100
    cs = np.concatenate(([0.0], np.cumsum(qv)))
    vol24 = np.full(n, np.nan)
    vol24[VOLWIN-1:] = cs[VOLWIN:] - cs[:n-VOLWIN+1]
    age_ok = (t - t[0]) >= NEWLIST_MS
    inwin = (t >= WIN_S) & (t < WIN_E)
    # need 48h of forward data available (else truncated exit at last bar - allow, flagged)
    cand = inwin & ok_lb & ok_vw & age_ok & (ret >= PUMP_LO) & (ret < PUMP_HI) & (vol24 >= MIN_QV)
    idx = np.nonzero(cand)[0]
    out = []
    last = -10**18
    for i in idx:
        if t[i] - last < COOLDOWN_MS: continue
        last = t[i]
        out.append((int(i), int(t[i]), float(c[i]), float(ret[i]), float(vol24[i])))
    return out, (t,o,h,l,c,qv)

if __name__ == "__main__":
    syms = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PQ,"*.npz")))
    trading = set(json.load(open(os.path.join(D,"trading_syms.json"))))
    allsig = {}
    stats = {"symbols":0,"delisted":0,"with_signals":0,"n_signals":0}
    for s in syms:
        try:
            sg, _ = sigs_for(s)
        except Exception as e:
            print("ERR", s, e); continue
        if sg is None: continue
        stats["symbols"] += 1
        if s not in trading: stats["delisted"] += 1
        if sg:
            allsig[s] = sg
            stats["with_signals"] += 1
            stats["n_signals"] += len(sg)
    json.dump(allsig, open(os.path.join(D,"signals.json"),"w"))
    delisted_with_sig = [s for s in allsig if s not in trading]
    stats["delisted_with_signals"] = len(delisted_with_sig)
    stats["signals_from_delisted"] = sum(len(allsig[s]) for s in delisted_with_sig)
    print(json.dumps(stats, indent=1))
