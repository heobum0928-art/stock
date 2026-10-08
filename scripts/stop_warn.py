"""
손절 조기경보 (stop_warn) — 2026-09-10 사용자 요청.
"기록만 하면 뭐해, 미리 손절신호를 알려줘"

**읽기 전용. 주문·설정 변경 없음. 봇 로직도 안 건드린다. 알림만 보낸다.**

계기: 2026-09-10 VTHOUSDT가 진입(09:03) 후 **2시간 56분** 만에 손절(-64.06 USDT,
증거금 -80.08%). 09시 봉 +33%, 10시 봉 +15%로 두 시간 만에 손절선을 넘었다.
5분 주기로 보면 충분히 미리 잡힌다.

## 경보 단계 (2026-09-09 실측 회복률 표에서 그대로 가져왔다 — 임의 조정 금지)
과거 133건을 "한때 역행한 폭(명목)"으로 나눈 결과:

| 역행폭(명목) | 최종 플러스로 끝난 비율 |
|---|---|
| 0~5%   | 100% |
| 5~10%  | 100% |
| 10~15% | 90% |
| **15~25%** | **67%**  ← 1차 경보(-20%)가 이 구간 |
| **25% 이상** | **21%**  ← 2차 경보(-25%)가 이 구간 |

- **-20%(명목)**: ⚠️ 주의. 아직 3분의 2는 돌아온다.
- **-25%(명목)**: 🚨 위험. 여기부터 회복률이 67% → 21%로 꺾인다.
- **-32%(명목)**: 🚨 손절 임박(손절선 -40%까지 8%p).
- **펀딩률 ≤ -0.5%**: ⚠️ 숏 쏠림. VTHO는 -1.8155%였다.
  ※ 이건 **아직 검정 안 된 관찰**이다. 참고용이며 손절 판단 근거로 쓰지 않는다.

**같은 종목·같은 단계는 한 번만 보낸다.** 봇은 계속 규칙대로 돈다. 자동 청산 없다.

Run: .venv/Scripts/python.exe scripts/stop_warn.py [--once] [--print-only]
watchdog 상주(POLL_SEC=300).
"""
import sys, os, json, time, argparse, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
KST = timezone(timedelta(hours=9))

# 경보 단계 — 2026-09-09 실측 표에서 그대로. 임의 조정 금지.
LEVELS = [(20.0, "⚠️", "주의", "과거 이 구간(15~25%)은 67%가 플러스로 끝났습니다."),
          (25.0, "🚨", "위험", "여기부터 회복률이 67% → **21%**로 꺾입니다."),
          (32.0, "🚨", "손절임박", "손절선(-40%)까지 8%p 남았습니다.")]
FUND_WARN = -0.5          # 펀딩률 % (숏이 내는 쪽)
POLL_SEC = 300
STATE = ROOT / "data" / "_stop_warn_state.json"
LOGF = ROOT / "logs" / "stop_warn.log"
LOGF.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [STOPWARN] %(message)s",
                    handlers=[logging.FileHandler(LOGF, encoding="utf-8"),
                              logging.StreamHandler(sys.stdout)])
log = logging.getLogger()
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def J(method, path, params=None):
    from bithumb.binance_guard import _signed
    r = _signed(method, path, params or {})
    return r.json() if hasattr(r, "json") else json.loads(r)


def pub(path, params=None):
    import requests
    r = requests.get("https://fapi.binance.com" + path, params=params or {}, timeout=20)
    return r.json() if r.status_code == 200 else None


def margin_positions():
    """마진 계좌의 숏 포지션을 선물과 같은 형태로 변환해 반환한다.
    마진은 '빌린 수량'이 곧 숏 수량이고, 평균 진입가는 체결내역에서 계산한다."""
    out = []
    try:
        from bithumb.margin_guard import _signed as ms
        r = ms("GET", "/sapi/v1/margin/account", {})
        acc = r.json() if hasattr(r, "json") else json.loads(r)
    except Exception as e:
        log.warning(f"마진 계좌 조회 실패: {e}")
        return out
    for u in acc.get("userAssets", []):
        asset = u["asset"]
        borrowed = float(u.get("borrowed", 0))
        if asset == "USDT" or borrowed <= 0:
            continue
        sym = asset + "USDT"
        try:
            r2 = ms("GET", "/sapi/v1/margin/myTrades", {"symbol": sym, "limit": 100})
            tr = r2.json() if hasattr(r2, "json") else json.loads(r2)
        except Exception:
            continue
        sells = [t for t in tr if not t["isBuyer"]]
        if not sells:
            continue
        q = sum(float(t["qty"]) for t in sells)
        if q <= 0:
            continue
        avg = sum(float(t["qty"]) * float(t["price"]) for t in sells) / q
        px = pub("/fapi/v1/premiumIndex", {"symbol": sym})
        mk = float(px["markPrice"]) if px and "markPrice" in px else None
        if mk is None:
            import requests
            try:
                mk = float(requests.get("https://api.binance.com/api/v3/ticker/price",
                                        params={"symbol": sym}, timeout=15).json()["price"])
            except Exception:
                continue
        # 잔여 차입이 체결 수량보다 훨씬 적으면 이미 대부분 청산된 찌꺼기 — 건너뛴다
        if borrowed < q * 0.1:
            continue
        out.append({"symbol": sym + "(마진)", "positionAmt": str(-borrowed),
                    "entryPrice": str(avg), "markPrice": str(mk),
                    "unRealizedProfit": str((avg - mk) * borrowed),
                    "updateTime": "margin"})
    return out


def cycle(print_only=False):
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    pos = [p for p in J("GET", "/fapi/v2/positionRisk") if float(p["positionAmt"]) != 0]
    # ★ 2026-09-11: 선물만 보고 있었다. 마진 숏(margin_short_trader 경로)이 통째로
    #   감시 밖이었다 — CLAUDE.md 1항("설정 파일이 둘이다")과 같은 계열의 누락이다.
    #   2026-09-11 TFUEL 사례에서 발견: 마진 포지션 15,923개 중 7,923개만 손절이 걸려
    #   있는데 경보기가 그 종목을 아예 보지 않고 있었다.
    pos += margin_positions()
    msgs = []
    for p in pos:
        sym = p["symbol"]; amt = float(p["positionAmt"])
        ep = float(p["entryPrice"]); mk = float(p["markPrice"])
        if ep <= 0 or amt == 0:
            continue
        is_short = amt < 0
        # 명목 역행폭(양수 = 손해 방향)
        adverse = (mk / ep - 1) * 100 if is_short else (1 - mk / ep) * 100
        key = f"{sym}|{p.get('updateTime','')}"

        for thr, icon, name, note in LEVELS:
            if adverse >= thr and st.get(f"{key}|{thr}") is None:
                stop_px = ep * (1.40 if is_short else 0.60)
                msgs.append(
                    f"{icon} 손절 {name} — {sym} {'숏' if is_short else '롱'}\n"
                    f"진입 {ep:.6g} → 현재 {mk:.6g}\n"
                    f"명목 {-adverse:+.1f}% / 증거금 {-adverse*float(p.get('leverage', 2) or 2):+.1f}%  (미실현 {float(p['unRealizedProfit']):+.2f} USDT)\n"
                    f"손절선 {stop_px:.6g} 까지 {abs(stop_px/mk-1)*100:+.1f}%\n\n{note}\n"
                    f"※ 봇은 계속 규칙대로 돕니다. 자동 청산 아님, 판단 참고용입니다.")
                st[f"{key}|{thr}"] = time.time()

        f = pub("/fapi/v1/premiumIndex", {"symbol": sym.replace("(마진)", "")})
        if f and isinstance(f, dict) and "lastFundingRate" in f and is_short:
            fr = float(f["lastFundingRate"]) * 100
            if fr <= FUND_WARN and st.get(f"{key}|fund") is None:
                msgs.append(
                    f"⚠️ 숏 쏠림 — {sym} 펀딩률 {fr:.4f}%\n"
                    f"8시간마다 이만큼 내고 있습니다(하루 약 {fr*3:.2f}%).\n"
                    f"숏이 이미 몰려 있다는 뜻입니다. 2026-09-10 VTHO는 -1.8155%였고 손절됐습니다.\n"
                    f"※ 검정되지 않은 관찰입니다. 참고용.")
                st[f"{key}|fund"] = time.time()

    live = {f"{p['symbol']}|{p.get('updateTime','')}" for p in pos}
    st = {k: v for k, v in st.items() if k.rsplit("|", 1)[0] in live}   # 닫힌 포지션 정리

    for m in msgs:
        log.info(m.replace("\n", " | "))
        if not print_only:
            try:
                from bithumb import notify
                ok = notify.send(m)
                log.info(f"텔레그램 {'성공' if ok else '실패/차단'}")
            except Exception as e:
                log.warning(f"텔레그램 실패: {e}")
        else:
            print(m + "\n")
    if not msgs:
        log.info(f"경보 없음 (포지션 {len(pos)}개)")
    tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(st), encoding="utf-8")
    os.replace(tmp, STATE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true"); ap.add_argument("--print-only", action="store_true")
    a = ap.parse_args()
    log.info(f"=== 손절 조기경보 시작 (경보 -20/-25/-32% 명목, 펀딩 {FUND_WARN}%, {POLL_SEC}초) ===")
    while True:
        try:
            cycle(a.print_only)
        except Exception as e:
            log.exception(f"사이클 오류: {e}")
        if a.once: break
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
