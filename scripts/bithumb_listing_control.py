"""#55 사후 대조군(통과 후 추가한 진단, 판정 아님): 같은 심볼·같은 규칙(48h·손절 5%·비용·펀딩)을
상장 +7일 / +30일 / +90일 뒤에 진입했을 때와 짝비교. 상장 효과인지 '그 코인들이 원래 숏에 유리한 기간이었는지' 구분."""
import sys, json, time, random
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bithumb_listing_short as b
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
random.seed(55)
sc = json.loads(b.SIM_CACHE.read_text(encoding="utf-8"))
t0 = json.loads(b.T0_CACHE.read_text(encoding="utf-8"))
CC = b.ROOT / "data" / "bithumb_listing_control_cache.json"
cache = json.loads(CC.read_text(encoding="utf-8")) if CC.exists() else {}
now_ms = time.time() * 1000

def run(sym, entry_ms):
    key = f"{sym}@{entry_ms}"
    if key in cache: return cache[key]
    k5 = b.fget("/fapi/v1/klines", symbol=sym, interval="5m", startTime=entry_ms, limit=b.HOLD_BARS + 2)
    if not k5 or len(k5) < b.HOLD_BARS or k5[0][0] > entry_ms + 10 * 60000:
        cache[key] = None; return None
    k5 = k5[:b.HOLD_BARS]; e = float(k5[0][1]); sl = e * 1.05
    ex, xi = float(k5[-1][4]), b.HOLD_BARS - 1
    for i, x in enumerate(k5):
        if float(x[2]) >= sl: ex, xi = max(sl, float(x[1])), i; break
    fr = b.fget("/fapi/v1/fundingRate", symbol=sym, startTime=k5[0][0], endTime=k5[xi][6], limit=1000) or []
    v = (e - ex) / e * 100 - b.COST + sum(float(f["fundingRate"]) for f in fr) * 100
    cache[key] = v; time.sleep(0.06); return v

for off in (7, 30, 90):
    pairs = []
    for m, v in sc.items():
        if v.get("status") != "ok": continue
        T = int(datetime.strptime(t0[m]["t0_utc"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
        em = ((T + off * 86400000 + 299999) // 300000) * 300000
        if em + 50 * 3600000 > now_ms: continue
        c = run(v["sym"], em)
        if c is None: continue
        pairs.append((v["raw_short"] - b.COST + v["fsum"], c, T))
    CC.write_text(json.dumps(cache), encoding="utf-8")
    a = np.array([p[0] for p in pairs]); c = np.array([p[1] for p in pairs]); d = a - c
    day = [datetime.fromtimestamp(p[2] / 1000, timezone.utc).strftime("%Y-%m-%d") for p in pairs]
    lo, hi = b.boot(list(d), day, 3000)
    print(f"+{off}일 대조: n={len(pairs)} 상장진입 {a.mean():+.2f}% / 대조 {c.mean():+.2f}% / 짝차이 {d.mean():+.2f}%p CI[{lo:+.2f},{hi:+.2f}]", flush=True)
