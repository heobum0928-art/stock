"""
CUSUM 롱 후보 알림 — 2026-09-17 사용자 요청 "CUSUM 자리 롱으로 하게".
**알림 + 모의 기록 전용. 주문 API 미호출.** 매매 결정은 사용자가 직접 한다.

봇과 같은 신호(7h 급등 + CUSUM 문턱 통과)가 나오면 텔레그램으로 알리고,
같은 건을 롱으로 모의 진입해 결과를 쌓는다(청산: 명목 -40% 손절 / 48h 만기 / 2배).

★ 참고: "CUSUM 거울상 롱"과 미러롱 2차(8,801건)는 백테스트에서 기각됐다.
  이 봇은 그 결론을 뒤집으려는 게 아니라, 사용자 결정에 맞춰 전방 실측을 쌓는 용도다.

Run: .venv/Scripts/python.exe scripts/cusum_long_alert.py
"""
import sys, os, csv, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import requests
from bithumb import notify

KST = timezone(timedelta(hours=9))
F = "https://fapi.binance.com"
POS = ROOT / "data" / "cusum_long_pos.json"
OUT = ROOT / "data" / "cusum_long_paper.csv"
CD = ROOT / "data" / "cusum_long_cooldown.json"
LOG = ROOT / "logs" / "cusum_long_alert.log"

# 봇과 동일한 신호 정의
BANDS = [(15.0, 30.0, 38.1, "완화구간"), (30.0, 40.0, 56.5, "원본구간")]
MIN_QVOL = 3_000_000
COOLDOWN_H = 12
POLL_SEC = 180
CUSUM_VOLWIN, CUSUM_K = 288, 0.3
# 모의 롱 청산 규칙(봇과 대칭)
STOP_PCT, HOLD_H, NOTIONAL, MARGIN, FEE_SIDE = 40.0, 48, 100.0, 50.0, 0.0006
FIELDS = ["symbol", "band", "cusum", "pump_7h", "entry_time", "exit_time", "entry_price",
          "exit_price", "hold_h", "reason", "pnl_pct_notional", "pnl_pct_margin", "pnl_usdt"]


def log(m):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} [CUSUM롱] {m}"
    print(line, flush=True)
    try:
        open(LOG, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass


def _j(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:
        return d


def _w(p, o):
    tmp = str(p) + ".tmp"
    Path(tmp).write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _get(path, **params):
    r = requests.get(F + path, params=params or None, timeout=20)
    r.raise_for_status()
    return r.json()


def cusum_score(sym):
    try:
        k = _get("/fapi/v1/klines", symbol=sym, interval="5m", limit=1000)
        n = len(k)
        if n < CUSUM_VOLWIN + 10:
            return None
        c = np.array([float(x[4]) for x in k])
        ret = np.zeros(n); ret[1:] = c[1:] / c[:-1] - 1.0
        cs1 = np.concatenate(([0.0], np.cumsum(ret)))
        cs2 = np.concatenate(([0.0], np.cumsum(ret * ret)))
        s1 = cs1[CUSUM_VOLWIN:] - cs1[:n + 1 - CUSUM_VOLWIN]
        s2 = cs2[CUSUM_VOLWIN:] - cs2[:n + 1 - CUSUM_VOLWIN]
        mean = s1 / CUSUM_VOLWIN
        std = np.sqrt(np.maximum(s2 / CUSUM_VOLWIN - mean ** 2, 1e-12))
        sf = np.full(n, np.nan); sf[CUSUM_VOLWIN:] = std[:n - CUSUM_VOLWIN]
        z = np.zeros(n); v = ~np.isnan(sf) & (sf > 1e-9); z[v] = ret[v] / sf[v]
        S = 0.0
        for i in range(CUSUM_VOLWIN, n):
            S = max(0.0, S + z[i] - CUSUM_K)
        return float(S)
    except Exception:
        return None


def scan(pos, cd):
    now = time.time()
    tick = _get("/fapi/v1/ticker/24hr")
    cand = [d for d in tick if d["symbol"].endswith("USDT") and float(d["quoteVolume"]) >= MIN_QVOL
            and float(d["priceChangePercent"]) >= 10]
    for d in cand:
        s = d["symbol"]
        if cd.get(s, 0) > now or s in pos:
            continue
        try:
            k = _get("/fapi/v1/klines", symbol=s, interval="1h", limit=8)
            r7 = (float(k[-1][4]) / float(k[0][1]) - 1) * 100
        except Exception:
            continue
        band = next((b for b in BANDS if b[0] <= r7 < b[1]), None)
        if not band:
            continue
        sc = cusum_score(s)
        time.sleep(0.1)
        if sc is None or sc < band[2]:
            continue
        px = float(_get("/fapi/v1/premiumIndex", symbol=s)["markPrice"])
        pos[s] = dict(band=band[3], cusum=round(sc, 1), pump=round(r7, 1), entry=px,
                      entry_ms=int(now * 1000), entry_iso=datetime.now(KST).isoformat())
        cd[s] = now + COOLDOWN_H * 3600
        _w(POS, pos); _w(CD, cd)
        stop = px * (1 - STOP_PCT / 100)
        msg = (f"[CUSUM롱후보] {s[:-4]} ({band[3]})\n"
               f"7시간 +{r7:.1f}% | CUSUM {sc:.1f} (문턱 {band[2]})\n"
               f"현재가 {px:.6g} | 참고 손절선(-40%) {stop:.6g}\n"
               f"※ 알림일 뿐, 주문 아님. 모의 롱으로 기록 중(48h)")
        notify.send(msg)
        log(f"후보 알림 {s} {band[3]} 7h+{r7:.1f}% CUSUM {sc:.1f} @{px:g}")


def settle(pos):
    now_ms = int(time.time() * 1000)
    for s in list(pos):
        p = pos[s]
        try:
            px = float(_get("/fapi/v1/premiumIndex", symbol=s)["markPrice"])
        except Exception:
            continue
        adv = (1 - px / p["entry"]) * 100               # 롱: 하락이 역행
        hold_h = (now_ms - p["entry_ms"]) / 3600000
        reason = None
        if adv >= STOP_PCT:
            px, reason = p["entry"] * (1 - STOP_PCT / 100), f"스탑-{STOP_PCT:.0f}%"
        elif hold_h >= HOLD_H:
            reason = f"{HOLD_H}h만기"
        if not reason:
            continue
        nom = (px / p["entry"] - 1) * 100
        net = NOTIONAL * nom / 100 - NOTIONAL * FEE_SIDE * 2
        net = max(net, -MARGIN)
        row = dict(symbol=s, band=p["band"], cusum=p["cusum"], pump_7h=p["pump"],
                   entry_time=p["entry_iso"], exit_time=datetime.now(KST).isoformat(),
                   entry_price=p["entry"], exit_price=px, hold_h=round(hold_h, 2), reason=reason,
                   pnl_pct_notional=round(nom, 2), pnl_pct_margin=round(net / MARGIN * 100, 2),
                   pnl_usdt=round(net, 2))
        new = not OUT.exists()
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        del pos[s]; _w(POS, pos)
        notify.send(f"[CUSUM롱결과] {s[:-4]} {reason} 명목 {nom:+.1f}% (모의 롱, 주문 없음)")
        log(f"모의 청산 {s} {reason} 명목{nom:+.1f}% 증거금{net/MARGIN*100:+.1f}%")


def main():
    log("=== CUSUM 롱 후보 알림 시작 (알림+모의 기록, 주문 없음) ===")
    while True:
        pos, cd = _j(POS, {}), {k: v for k, v in _j(CD, {}).items() if v > time.time()}
        try:
            settle(pos)
            scan(pos, cd)
        except Exception as e:
            log(f"루프 오류: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
