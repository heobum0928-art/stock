"""
상태 심박 (status_heartbeat) — 2026-09-06 사용자 요청("밖에 있는데 안을 빼꼼히 보고 싶다").

기존 알림은 전부 **사건 기반**이다(진입/청산/손절실패/역행경보). 아무 일 없으면 조용한데,
밖에서는 그 침묵이 "정상"인지 "봇이 죽었다"인지 구분되지 않는다. 이 스크립트가 그 구멍을 메운다.

보내는 것: 포지션 현황(telegram_status와 동일) + 봇 생존 + 지갑 + 오늘 확정손익.
읽기 전용 — 주문·설정 변경 없음. GET만.

무음시간(config.yaml telegram.quiet_start~quiet_end)에는 정상 심박을 보내지 않는다.
단, **핵심 봇이 죽었으면 🚨를 붙여 무음시간에도 강제 발송**한다(notify.send가 🚨를 force 처리).

watchdog ONESHOT 등록, 기본 30분 간격.
수동: .venv/Scripts/python.exe scripts/status_heartbeat.py [--print-only]
"""
import sys, os, re, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)                      # notify/telegram_status가 상대경로 config.yaml을 읽는다
KST = timezone(timedelta(hours=9))

# 이 봇들이 하나라도 없으면 심박에 🚨를 붙인다(= 무음시간에도 도달)
CORE_BOTS = ["margin_short_trader.py", "margin_short_wide_trader.py",
             "core_leveraged.py", "tg_bot.py", "watchdog.py"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def alive_bots():
    """실행 중인 봇 스크립트 이름 집합. psutil 실패 시 None(판정 보류)."""
    try:
        import psutil
    except Exception:
        return None
    names = set()
    for p in psutil.process_iter(["cmdline"]):
        a = p.info.get("cmdline") or []
        if not a or "python" not in a[0].lower():
            continue
        for x in a:
            if x.endswith(".py"):
                names.add(os.path.basename(x))
    return names


def wallet_line():
    try:
        from bithumb.binance_guard import _signed
        bal = [x for x in _signed("GET", "/fapi/v2/balance").json() if x["asset"] == "USDT"][0]
        btc = [p for p in _signed("GET", "/fapi/v2/positionRisk").json() if p["symbol"] == "BTCUSDT"]
        out = f"지갑 {float(bal['balance']):.0f} / 가용 {float(bal['availableBalance']):.0f} USDT"
        if btc and float(btc[0]["positionAmt"]) != 0:
            b = btc[0]
            out += (f"\nBTC롱 {float(b['positionAmt']):.3f} @{float(b['entryPrice']):,.0f}"
                    f" → {float(b['markPrice']):,.0f} ({float(b['unRealizedProfit']):+.1f})")
        return out
    except Exception as e:
        return f"지갑 조회 실패: {str(e)[:60]}"


def today_realized():
    try:
        import pandas as pd
        d = datetime.now(KST).strftime("%Y-%m-%d")
        led = pd.concat([pd.read_csv(ROOT / "data" / "margin_short_ledger.csv"),
                         pd.read_csv(ROOT / "data" / "margin_short_wide_ledger.csv")])
        x = led[led.exit_time.str[:10] == d]
        if not len(x):
            return "오늘 확정: 없음"
        items = ", ".join(f"{r.symbol[:-4]} {r.net_pnl_usdt:+.1f}" for r in x.itertuples())
        return f"오늘 확정 {len(x)}건 {x.net_pnl_usdt.sum():+.1f} USDT ({items})"
    except Exception as e:
        return f"오늘 확정 조회 실패: {str(e)[:60]}"


STAMP = ROOT / "data" / "_status_heartbeat_last.txt"
MIN_GAP_SEC = 1500          # 25분 — 워치독판과 수동/임시 루프가 겹쳐도 중복 발송 안 되게


def _too_soon() -> bool:
    try:
        import time
        return (time.time() - float(STAMP.read_text().strip())) < MIN_GAP_SEC
    except Exception:
        return False


def _stamp():
    # ★ 2026-09-06 B4: 워치독판과 임시 루프가 동시에 쓰면 부분 읽기로 중복방지가 무력화된다.
    #   임시파일에 쓰고 os.replace로 원자적 교체한다.
    try:
        import time
        tmp = STAMP.with_suffix(".tmp")
        tmp.write_text(str(time.time()), encoding="utf-8")
        os.replace(tmp, STAMP)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--print-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="중복방지 무시하고 발송")
    a = ap.parse_args()
    now = datetime.now(KST)
    if not a.print_only and not a.force and _too_soon():
        print("최근에 이미 보냄 — 생략(중복 방지)")
        return
    try:
        from scripts import telegram_status
        pos = re.sub(r"</?(b|i|code|pre)>", "", telegram_status.build_text()).split("[그림자함대]")[0].strip()
    except Exception as e:
        pos = f"[포지션현황]\n조회 실패: {str(e)[:80]}"

    names = alive_bots()
    if names is None:
        health = "봇 생존: 확인 불가(psutil 없음)"
        dead = []
    else:
        dead = [b for b in CORE_BOTS if b not in names]
        # ★ 2026-09-06 B5: 워치독의 정상 재시작은 kill→3초→start→5초로 8~11초의 부재 창을
        #   만든다. 단발 샘플로 판정하면 그 창에 걸려 새벽에 헛된 🚨가 간다(🚨는 무음시간을
        #   강제로 뚫는다). 죽은 것으로 보이면 15초 뒤 한 번 더 확인해 둘 다 없을 때만 보고한다.
        if dead:
            import time as _t; _t.sleep(15)
            again = alive_bots() or set()
            dead = [b for b in dead if b not in again]
        health = "봇 정상 (핵심 5종)" if not dead else "봇 중단: " + ", ".join(b.replace(".py", "") for b in dead)

    head = f"🫀 {now:%m/%d %H:%M} 상태"
    if dead:
        head = f"🚨 {now:%m/%d %H:%M} 상태 — 봇 중단 감지"
    text = "\n".join([head, "", pos, "", health, wallet_line(), today_realized()])

    print(text)
    if a.print_only:
        return
    try:
        from bithumb import notify
        ok = notify.send(text)
        if ok:
            _stamp()
        print(f"\n텔레그램 전송: {'성공' if ok else '생략(무음시간 또는 실패)'}")
    except Exception as e:
        print("텔레그램 전송 실패:", e)


if __name__ == "__main__":
    main()
