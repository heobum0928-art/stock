"""
기록 파수꾼 — 매일 1회, 기록 체계가 조용히 망가지는 것을 감지해 텔레그램으로 보고.

배경(왜 필요한가): 2026-08-20 기록감사에서 나온 문제들의 공통점은 **아무도 안 봐서
오래 방치됐다**는 것이다.
  - 펀딩비 누락으로 손익이 29 USDT 어긋난 상태로 **한 달** 지남
  - breadth_events.csv가 7/5부터 쌓였는데 **아무도 안 읽어서** 상관 리스크를
    "판단 불가"라고 결론냈었음(실제로는 답할 수 있는 데이터가 있었음)
  - DEADLINES.md가 git 추적조차 안 된 채로 있었고, 그 안에만 있던 정정 EV가
    유실 직전이었음
  - WEEKLY.md가 59일 지난 날짜를 매주 새로 찍어내는 중
  - 8/19 감사가 지적한 것들이 8/20에 대부분 그대로

전부 "알 수 있었는데 안 봤다"이지 "알 수 없었다"가 아니다. 그래서 매일 한 번
기계가 훑고, 이상하면 시끄럽게 만든다.

이 스크립트가 검사하는 것:
  1. 사전확정 문서 백업/무결성 (판정의 전제)
  2. 봇별 최근 산출물 — 돌고는 있는데 아무것도 안 만드는 봇 감지
  3. 쓰기만 하고 아무도 안 읽는 데이터 파일 (breadth 사례 재발 방지)
  4. 마감일 임박 (DEADLINES.md 자동 파싱)
  5. 원장 대조가 최근 돌았는지 (감시자 자신도 감시)
  6. 51건 관문 도달 임박
  7. 미커밋 상태로 오래 방치된 변경

★ 읽기전용: 주문 API 미호출. 파일도 읽기만 한다.
Run: python scripts/record_guard.py  (스케줄러 하루 1회 상정)
"""
import sys, os, re, csv, json, glob, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)

LOCKED_DOCS = ["docs/51GATE_CRITERIA.md", "docs/51GATE_UNITS.md", "docs/DEADLINES.md"]
GATE_TARGET = 51
STALE_BOT_HOURS = 24          # 이 시간 넘게 산출물이 없으면 이상
STALE_COMMIT_DAYS = 3         # 미커밋 변경이 이만큼 묵으면 경고
DEADLINE_WARN_DAYS = 7        # 마감일 D-7부터 알림

# 봇 → 그 봇이 살아있으면 갱신돼야 하는 산출물. 로그는 봇이 헛돌아도 갱신되므로
# "실제 결과물"을 본다. None이면 로그로 대체(로깅 전용 봇 등).
BOT_OUTPUTS = {
    "margin_short_trader": ["data/margin_short_pos.json"],
    "shadow_fleet": ["data/shadow_fleet_pos.json", "data/shadow_signals.csv"],
    "breadth_monitor": ["data/breadth_events.csv"],
    "futures_logger": ["data/futures_signals.csv"],
    "orderflow_logger": ["data/orderflow_events.csv"],
    "crossex_logger": ["data/crossex_events.csv"],
    "volume_radar": ["data/volume_radar_events.csv"],
    "igniter_alert": ["data/igniter_events.csv"],
    "bc_rule_shadow_paper": ["data/bc_rule_shadow_trades.csv"],
    "oi_divergence_short_paper": ["data/oi_div_paper_trades.csv"],
    "alt_momentum_long_paper": ["data/alt_momentum_long_pos.json"],
    "rsi_extreme_short_paper": ["data/rsi_short_trades.csv"],
}

issues = []      # (심각도, 한줄) — 심각도 0=위험 1=주의 2=참고


def add(sev, msg):
    issues.append((sev, msg))


def _git(*a):
    r = subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout or "", r.stderr or ""


def age_h(p):
    return (NOW - datetime.fromtimestamp(os.path.getmtime(p), KST)).total_seconds() / 3600


# ── 1. 사전확정 문서 ────────────────────────────────────────────────────────
def check_locked_docs():
    for d in LOCKED_DOCS:
        p = ROOT / d
        if not p.exists():
            add(0, f"{d} 파일 없음")
            continue
        _, out, _ = _git("log", "--oneline", "-1", "--", d)
        if not out.strip():
            add(0, f"{d} git 미백업 — 수정해도 흔적이 안 남음")
            continue
        _, out, _ = _git("diff", "--stat", "HEAD", "--", d)
        if out.strip():
            add(0, f"{d} 커밋 후 수정됨 — 판정 거부 상태. 의도한 수정이면 커밋할 것")


# ── 2. 봇 산출물 ────────────────────────────────────────────────────────────
def check_bots():
    for bot, outs in BOT_OUTPUTS.items():
        fresh = []
        for o in outs:
            p = ROOT / o
            if p.exists():
                fresh.append(age_h(p))
        if not fresh:
            add(1, f"[{bot}] 산출물 파일이 아예 없음")
            continue
        if min(fresh) > STALE_BOT_HOURS:
            add(1, f"[{bot}] {min(fresh):.0f}시간째 산출물 갱신 없음 — 죽었거나 헛도는 중")


# ── 3. 아무도 안 읽는 데이터 ────────────────────────────────────────────────
def check_orphan_data():
    """쓰기는 되는데 읽는 코드가 없는 파일. breadth_events.csv가 한 달간
    이 상태였고, 그래서 상관 리스크를 '판단 불가'로 잘못 결론냈었다."""
    code = ""
    for s in glob.glob(str(ROOT / "scripts" / "*.py")) + glob.glob(str(ROOT / "bithumb" / "*.py")):
        try:
            code += open(s, encoding="utf-8", errors="ignore").read()
        except Exception:
            pass
    orphans = []
    for f in glob.glob(str(ROOT / "data" / "*.csv")):
        base = os.path.basename(f)
        if os.path.getsize(f) < 50_000:      # 작은 건 방치돼도 손해가 적음
            continue
        if age_h(f) > 24 * 14:               # 2주 넘게 안 갱신되면 이미 죽은 것 — 별건
            continue
        # 파일명이 코드에 2번 이상 나오면 최소한 생성+참조는 되는 것으로 본다
        if code.count(base) + code.count(base.rsplit(".", 1)[0]) < 2:
            orphans.append((base, os.path.getsize(f) / 1024 / 1024))
    for b, mb in orphans:
        add(2, f"{b} ({mb:.0f}MB) 계속 쌓이는데 읽는 코드가 없음 — 쓸 데가 없으면 중단 검토")


# ── 4. 마감일 ───────────────────────────────────────────────────────────────
def check_deadlines():
    p = ROOT / "docs" / "DEADLINES.md"
    if not p.exists():
        return
    txt = p.read_text(encoding="utf-8")
    for m in re.finditer(r"마감:\s*(\d{4})-(\d{2})-(\d{2})", txt):
        d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=KST)
        left = (d - NOW).days
        if left < 0:
            add(0, f"마감일 {d:%Y-%m-%d} 이미 지남 ({-left}일 경과) — 판정했는가?")
        elif left <= DEADLINE_WARN_DAYS:
            add(1, f"마감일 {d:%Y-%m-%d} D-{left}")


# ── 5. 원장 대조가 살아있는지 (감시자 자신을 감시) ───────────────────────────
def check_reconcile():
    log = ROOT / "logs" / "ledger_reconcile.log"
    if not log.exists():
        add(1, "원장 대조 로그 없음 — ledger_reconcile.py가 한 번도 안 돌았을 수 있음")
        return
    a = age_h(log)
    if a > 48:
        add(0, f"원장 대조가 {a/24:.1f}일째 안 돎 — 손익 불일치를 감지할 장치가 꺼진 상태")


# ── 6. 51건 관문 ────────────────────────────────────────────────────────────
def check_gate():
    p = ROOT / "data" / "margin_short_trades.csv"
    if not p.exists():
        return None
    n = sum(1 for r in csv.DictReader(open(p, encoding="utf-8")) if r.get("exit_time"))
    if n >= GATE_TARGET:
        add(0, f"★ {GATE_TARGET}건 도달 ({n}건) — gate_eval.py 실행해 판정할 것")
    elif GATE_TARGET - n <= 2:
        add(1, f"{GATE_TARGET}건까지 {GATE_TARGET-n}건 남음 (현재 {n}건)")
    return n


# ── 7. 미커밋 방치 ──────────────────────────────────────────────────────────
def check_uncommitted():
    _, out, _ = _git("status", "--porcelain", "--untracked-files=no")
    changed = [l[3:] for l in out.splitlines() if l.strip()]
    if not changed:
        return
    oldest = 0
    for f in changed:
        p = ROOT / f
        if p.exists():
            oldest = max(oldest, age_h(p) / 24)
    sev = 0 if oldest > STALE_COMMIT_DAYS else 2
    add(sev, f"미커밋 변경 {len(changed)}건 (가장 오래된 것 {oldest:.1f}일) — "
             f"{'백업 안 된 상태로 방치 중' if sev == 0 else '확인 요망'}")


def main():
    check_locked_docs()
    check_bots()
    check_orphan_data()
    check_deadlines()
    check_reconcile()
    n = check_gate()
    check_uncommitted()

    issues.sort(key=lambda x: x[0])
    danger = [m for s, m in issues if s == 0]
    warn = [m for s, m in issues if s == 1]
    info = [m for s, m in issues if s == 2]

    print(f"기록 파수꾼 {NOW:%Y-%m-%d %H:%M} — 위험 {len(danger)} / 주의 {len(warn)} / 참고 {len(info)}")
    for lbl, group in (("[위험]", danger), ("[주의]", warn), ("[참고]", info)):
        for m in group:
            print(f"  {lbl} {m}")
    if not issues:
        print("  이상 없음")

    # 위험이 있거나 마감일이 임박하면 텔레그램. 참고만 있으면 조용히 넘어간다
    # (매일 시끄러우면 결국 안 보게 되고, 그게 이 프로젝트의 원래 실패 모드다).
    if danger or warn:
        lines = [f"📋 기록점검 {NOW:%m-%d}"]
        if n is not None:
            lines.append(f"margin_short {n}/{GATE_TARGET}건")
        lines += [f"🚨 {m}" for m in danger] + [f"⚠️ {m}" for m in warn]
        try:
            from bithumb import notify
            notify.send("\n".join(lines), force=True)
        except Exception as e:
            print(f"  (텔레그램 전송 실패: {e})")


if __name__ == "__main__":
    main()
