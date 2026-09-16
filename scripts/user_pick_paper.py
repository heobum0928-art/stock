"""
사용자 종목 선정 검정 — docs/PREREG_USER_PICK.md 기준. **순수 모의, 주문 API 미호출.**

사용자가 종목을 말하면 그 시점 가격으로 기록하고, 같은 시각 무작위 종목 1건을 대조군으로
함께 기록한다. 청산은 규칙 고정(명목 -40% 손절 / 48h 만기 / 트레일링 없음, 2배).

사용법:
  기록:  python scripts/user_pick_paper.py add SYN short        (롱이면 long)
  감시:  python scripts/user_pick_paper.py                      (루프, watchdog 등록용)
  현황:  python scripts/user_pick_paper.py status
  판정:  python scripts/user_pick_paper.py eval                 (30건 도달 시에만 의미)
"""
import sys, os, json, time, csv, random
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

KST = timezone(timedelta(hours=9))
FAPI = "https://fapi.binance.com"
POS = ROOT / "data" / "user_pick_pos.json"
OUT = ROOT / "data" / "user_pick_trades.csv"
LOG = ROOT / "logs" / "user_pick_paper.log"

# ── 사전등록 고정값 ──
NOTIONAL, MARGIN = 100.0, 50.0
LEV = 2.0
# 트랙별 고정 규칙 — PREREG_USER_PICK.md(swing) / PREREG_USER_PICK_SCALP.md(scalp)
MODES = {"swing": dict(stop=40.0, hold_h=48), "scalp": dict(stop=15.0, hold_h=6)}
STOP_PCT = 40.0            # 명목 기준 역행 (swing 기본, 하위호환)
HOLD_H = 48
FEE_SIDE = 0.0006
MIN_QVOL = 3_000_000
LIQ_SHORT, LIQ_LONG = 42.857, 47.368
FIELDS = ["pick_id", "mode", "kind", "coin", "side", "entry_time", "exit_time", "entry_price",
          "exit_price", "hold_h", "reason", "pnl_pct_notional", "pnl_pct_margin",
          "pnl_usdt", "funding_usdt", "note"]


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    line = f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} [PICK] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _get(path, **params):
    r = requests.get(FAPI + path, params=params or None, timeout=20)
    r.raise_for_status()
    return r.json()


def load():
    if POS.exists():
        try:
            return json.loads(POS.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save(rows):
    tmp = str(POS) + ".tmp"
    Path(tmp).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, POS)


def mark(sym):
    return float(_get("/fapi/v1/premiumIndex", symbol=sym)["markPrice"])


def universe():
    return [d["symbol"] for d in _get("/fapi/v1/ticker/24hr")
            if d["symbol"].endswith("USDT") and float(d["quoteVolume"]) >= MIN_QVOL]


def funding_paid(sym, s_ms, e_ms, notional, side):
    """숏은 받으면 +, 롱은 반대."""
    try:
        ev = _get("/fapi/v1/fundingRate", symbol=sym, startTime=s_ms, endTime=e_ms, limit=1000)
    except Exception:
        return 0.0
    tot = sum(float(x["fundingRate"]) for x in ev) * notional
    return tot if side == "short" else -tot


def add(coin, side, mode="swing"):
    coin = coin.upper().replace("USDT", "")
    side = side.lower()
    mode = mode.lower()
    assert side in ("long", "short"), "방향은 long 또는 short"
    assert mode in MODES, f"모드는 {list(MODES)}"
    sym = coin + "USDT"
    px = mark(sym)
    now_ms = int(time.time() * 1000)
    rng = random.Random(now_ms)
    uni = [s for s in universe() if s != sym]
    ctrl_sym = rng.choice(uni)
    ctrl_px = mark(ctrl_sym)
    pid = f"{datetime.now(KST).strftime('%m%d%H%M%S')}-{coin}"
    rows = load()
    for kind, s, p in (("pick", sym, px), ("control", ctrl_sym, ctrl_px)):
        rows.append(dict(pick_id=pid, mode=mode, kind=kind, coin=s[:-4], symbol=s, side=side,
                         entry_price=p, entry_ms=now_ms,
                         entry_time=datetime.now(KST).isoformat(), mfe=p, mae=p))
    save(rows)
    cfg = MODES[mode]
    log(f"기록 {pid} [{mode}] | 픽 {coin} {side} @{px:g} | 대조군 {ctrl_sym[:-4]} @{ctrl_px:g}")
    print(f"\n  ▶ 픽:    {coin:10s} {side:5s} @ {px:g}")
    print(f"  ▶ 대조군: {ctrl_sym[:-4]:10s} {side:5s} @ {ctrl_px:g}   (무작위, 시드={now_ms})")
    print(f"  청산 규칙[{mode}]: 명목 -{cfg['stop']:.0f}% 손절 / {cfg['hold_h']}h 만기 / 2배 · 모의(주문 없음)")
    n = len({r['pick_id'] for r in rows if r.get('mode', 'swing') == mode})
    print(f"  {mode} 트랙 누적 {n}/30건 (판정: 30건 또는 2026-12-31)")


def adverse_pct(side, entry, px):
    """역행률(+면 손실 방향)."""
    return (px / entry - 1) * 100 if side == "short" else (1 - px / entry) * 100


def close_row(r, px, reason, now_ms):
    side = r["side"]
    entry = r["entry_price"]
    nom = -adverse_pct(side, entry, px)                      # 명목 손익률
    gross = NOTIONAL * nom / 100
    fee = -NOTIONAL * FEE_SIDE * 2
    fund = funding_paid(r["symbol"], r["entry_ms"], now_ms, NOTIONAL, side)
    net = gross + fee + fund
    liq = LIQ_SHORT if side == "short" else LIQ_LONG
    if adverse_pct(side, entry, px) >= liq or net < -MARGIN:
        net, reason = -MARGIN, f"강제청산({reason})"
    hold_h = (now_ms - r["entry_ms"]) / 3600_000
    row = dict(pick_id=r["pick_id"], mode=r.get("mode", "swing"), kind=r["kind"],
               coin=r["coin"], side=side,
               entry_time=r["entry_time"],
               exit_time=datetime.fromtimestamp(now_ms / 1000, KST).isoformat(),
               entry_price=entry, exit_price=px, hold_h=round(hold_h, 2), reason=reason,
               pnl_pct_notional=round(nom, 3), pnl_pct_margin=round(net / MARGIN * 100, 3),
               pnl_usdt=round(net, 3), funding_usdt=round(fund, 4), note="")
    new = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    log(f"청산 {r['pick_id']}/{r['kind']} {r['coin']} {reason} "
        f"명목{nom:+.1f}% 증거금{net/MARGIN*100:+.1f}% ({net:+.2f}U)")
    return row


def watch_once():
    rows = load()
    if not rows:
        return
    now_ms = int(time.time() * 1000)
    keep = []
    for r in rows:
        try:
            px = mark(r["symbol"])
        except Exception:
            keep.append(r); continue
        adv = adverse_pct(r["side"], r["entry_price"], px)
        r["mae"] = max(r.get("mae", px), px) if r["side"] == "short" else min(r.get("mae", px), px)
        hold_h = (now_ms - r["entry_ms"]) / 3600_000
        cfg = MODES[r.get("mode", "swing")]
        if adv >= cfg["stop"]:
            close_row(r, r["entry_price"] * ((1 + cfg["stop"] / 100) if r["side"] == "short"
                                             else (1 - cfg["stop"] / 100)), f"스탑-{cfg['stop']:.0f}%", now_ms)
        elif hold_h >= cfg["hold_h"]:
            close_row(r, px, f"{cfg['hold_h']}h만기", now_ms)
        else:
            keep.append(r)
    if len(keep) != len(rows):
        save(keep)


def status():
    rows = load()
    done = list(csv.DictReader(open(OUT, encoding="utf-8"))) if OUT.exists() else []
    picks_done = len({r["pick_id"] for r in done})
    for m in MODES:
        dm = len({r["pick_id"] for r in done if (r.get("mode") or "swing") == m})
        om = len({r["pick_id"] for r in rows if r.get("mode", "swing") == m})
        print(f"[{m:5s}] 완료 {dm}/30건 | 보유 중 {om}건")
    for r in rows:
        try:
            px = mark(r["symbol"])
            adv = adverse_pct(r["side"], r["entry_price"], px)
            cfg = MODES[r.get("mode", "swing")]
            print(f"  [{r.get('mode','swing'):5s}] {r['kind']:8s} {r['coin']:10s} {r['side']:5s} "
                  f"명목 {-adv:+6.2f}% ({(time.time()*1000 - r['entry_ms'])/3600000:.1f}/{cfg['hold_h']}h)")
        except Exception:
            print(f"  {r['kind']:8s} {r['coin']:10s} 조회실패")


def evaluate(mode="swing"):
    import numpy as np
    if not OUT.exists():
        print("표본 없음"); return
    rows = [r for r in csv.DictReader(open(OUT, encoding="utf-8"))
            if (r.get("mode") or "swing") == mode]
    if not rows:
        print(f"[{mode}] 표본 없음"); return
    print(f"=== 트랙: {mode} (스탑 -{MODES[mode]['stop']:.0f}% / {MODES[mode]['hold_h']}h) ===")
    by = {}
    for r in rows:
        by.setdefault(r["pick_id"], {})[r["kind"]] = r
    pairs = [(v["pick"], v["control"]) for v in by.values() if "pick" in v and "control" in v]
    if not pairs:
        print("짝 완성된 표본 없음"); return
    d = np.array([float(p["pnl_pct_margin"]) - float(c["pnl_pct_margin"]) for p, c in pairs])
    pk = np.array([float(p["pnl_pct_margin"]) for p, _ in pairs])
    ct = np.array([float(c["pnl_pct_margin"]) for _, c in pairs])
    days = np.array([datetime.fromisoformat(p["entry_time"]).astimezone(KST).toordinal()
                     for p, _ in pairs])
    print(f"[판정] 짝 {len(d)}건 (PREREG_USER_PICK.md 기준, 30건 도달 시 유효)")
    print(f"  픽 평균 {pk.mean():+.2f}%  대조군 평균 {ct.mean():+.2f}%  (증거금 기준)")
    print(f"  짝차이 평균 {d.mean():+.2f}%p  중앙값(참고) {np.median(d):+.2f}%p")
    rng = np.random.default_rng(20260916)
    uq = np.unique(days); idx = {u: np.nonzero(days == u)[0] for u in uq}
    ms = []
    for _ in range(4000):
        pick = rng.integers(0, len(uq), len(uq))
        sel = np.concatenate([idx[uq[p]] for p in pick])
        ms.append(d[sel].mean())
    lo, hi = np.percentile(ms, [2.5, 97.5])
    mde = (1.96 + 0.84) * d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else float("nan")
    print(f"  95% CI [{lo:+.2f}, {hi:+.2f}]%p — 일블록 {len(uq)}일, 4000회, 시드 20260916")
    print(f"  MDE(95%·80%) {mde:.2f}%p")
    if d.mean() > 0 and lo > 0:
        v = "H1 → 선정 능력 확인"
    elif d.mean() > 0 and abs(d.mean()) >= mde:
        v = "H2 → 유망, 표본 늘려 재확인"
    elif abs(d.mean()) < mde:
        v = "H3 → 판별 불가"
    else:
        v = "H4 → 선정 능력 없음"
    print(f"  ▶ {v}")
    if len(d) < 30:
        print(f"  ※ 아직 {len(d)}/30건 — 판정일 전이므로 참고값이다.")


def main():
    a = sys.argv[1:]
    if a and a[0] == "add":
        add(a[1], a[2] if len(a) > 2 else "long", a[3] if len(a) > 3 else "swing")
    elif a and a[0] == "status":
        status()
    elif a and a[0] == "eval":
        for m in ([a[1]] if len(a) > 1 else list(MODES)):
            evaluate(m); print()
    else:
        log(f"=== 사용자 픽 모의 감시 시작 (스탑 -{STOP_PCT:.0f}% / {HOLD_H}h / 주문 없음) ===")
        while True:
            try:
                watch_once()
            except Exception as e:
                log(f"루프 오류: {e}")
            time.sleep(300)


if __name__ == "__main__":
    main()
