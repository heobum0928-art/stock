"""
51건 관문 / 9-19 존속 판정 계산기 — 사람이 손계산하지 않게 만드는 단일 관문.

배경(왜 이게 필요한가):
  2026-08-20에 담당자가 51GATE_CRITERIA.md의 "-0.93"을 %로 착각(실제는 USDT)해
  "기준2 미충족·악화"라고 오판하고, 그 틀린 전제로 외부 AI 6곳에 자문을 구했다.
  같은 날 두 번째로 원장 잣대 46건 값을 CSV 잣대 39건 기준값과 비교해(잣대 혼용)
  또 오판할 뻔했다. 두 사고 모두 "사람이 문서를 읽고 손으로 계산"해서 났다.
  문서에 주의사항을 적는 것으로는 안 막힌다(단위 결함은 8/19 감사가 이미 지적했고
  다음날 그대로 발현됐다). 그래서 계산을 코드로 옮기고, 틀린 비교는 실행이
  안 되게 만든다.

이 스크립트가 구조적으로 막는 것:
  ① 단위 혼용   — Metric에 단위가 붙어 있고, 다른 단위끼리 비교하면 예외
  ② 잣대 혼용   — CSV/원장 잣대가 다르면 비교 자체가 예외
  ③ 표본 혼용   — 표본 정의(원본/버그조정)가 다르면 예외
  ④ 문서 몰래수정 — 사전확정 문서가 git 커밋본과 다르면 **판정 거부**
  ⑤ 미백업     — 사전확정 문서가 git에 없으면 **판정 거부**
  ⑥ 오염 데이터 — 원장 건별값 오염(연속거래 선점)을 자동 감지해 보정값 병기

판정 기준의 출처(이 스크립트가 정하지 않는다):
  docs/51GATE_CRITERIA.md  — 4개 기준, 2026-08-17 사전확정, 수정 금지
  docs/51GATE_UNITS.md     — 단위/잣대/이상치 임계값 해석, 2026-08-20 결과 보기 전 고정
  docs/DEADLINES.md        — 9/19 존속 판정 기준, 사전확정

★ 읽기전용: 주문 API 미호출. 거래 CSV도 읽기만 한다.
Run: python scripts/gate_eval.py
"""
import sys, csv, json, math, random, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
TRADES = ROOT / "data" / "margin_short_trades.csv"
LEDGER = ROOT / "data" / "margin_short_ledger.csv"

# 판정 전제가 되는 사전확정 문서 — 이 중 하나라도 미커밋/수정됐으면 판정 거부
LOCKED_DOCS = ["docs/51GATE_CRITERIA.md", "docs/51GATE_UNITS.md", "docs/DEADLINES.md"]

# 51GATE_UNITS.md에서 결과 보기 전에 고정한 값들 (여기서 새로 정하는 게 아니라 옮겨온 것)
OUTLIER_PCT = -100.0                      # 이상치 정의: 증거금 대비 -100% 초과(설계 최대손실 -80%)
GATE2_BASELINE_USDT = -0.930              # 기준2 기준값(39건 시점, CSV 잣대)
GATE2_BASELINE_N = 39
GATE1_MIN_LOWER = 45.0                    # 기준1 Wilson 하한 최소치(%)
GATE4_MAX_GAP_PP = 10.0                   # 기준4 승률 허용 하락폭(%p)
GATE4_CUTOFF = datetime(2026, 8, 16, 23, 0, tzinfo=KST)   # 원문 "확인 방법" 열 기준
GATE4_CUTOFF_REAL = datetime(2026, 8, 15, 23, 21, tzinfo=KST)  # 실제 캡전환(병기용)
TARGET_N = 51


class UnitMismatch(Exception):
    """단위/잣대/표본이 다른 값을 비교하려 할 때. 2026-08-20 사고의 재발 방지선."""


class Metric:
    """숫자 하나가 절대 혼자 다니지 않게 한다 — 항상 (값, 단위, 잣대, 표본)을 달고 다닌다."""

    def __init__(self, value, unit, instrument, sample):
        self.value, self.unit = value, unit
        self.instrument, self.sample = instrument, sample

    def _check(self, other):
        for attr, label in (("unit", "단위"), ("instrument", "잣대"), ("sample", "표본")):
            a, b = getattr(self, attr), getattr(other, attr)
            if a != b:
                raise UnitMismatch(
                    f"{label}가 다른 값끼리 비교했습니다: {a} vs {b}\n"
                    f"  좌: {self}\n  우: {other}\n"
                    f"  → 기준값도 같은 {label}로 재계산해야 합니다 "
                    f"(docs/51GATE_UNITS.md '잣대 사용 규칙' 참조)")

    def __ge__(self, other):
        self._check(other)
        return self.value >= other.value

    def __str__(self):
        v = f"{self.value:+.3f}" if self.unit == "USDT" else f"{self.value:+.2f}{self.unit}"
        return f"{v} [{self.unit}/{self.instrument}/{self.sample}]"


def refuse(msg):
    print("\n" + "=" * 68)
    print("판정 거부 — 전제조건 미충족")
    print("=" * 68)
    print(msg)
    sys.exit(1)


def _git(*args):
    # encoding 명시 필수 — 커밋 메시지가 한글이라 Windows 기본 cp949로는 디코딩 실패한다
    r = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout or "", r.stderr or ""


def check_preconditions():
    """사전확정 문서가 (a)git에 있고 (b)커밋 이후 수정되지 않았는지. 하나라도 실패하면 판정 거부.

    이유: 사후편향 방어는 "문서를 결과 보기 전에 고정했다"는 것이 증명 가능할 때만
    성립한다. 2026-08-20 감사에서 DEADLINES.md가 git 추적조차 안 되고 있었음이
    발견됐다 — '수정 금지'를 스스로 선언한 문서가 수정해도 흔적이 안 남는 상태였다."""
    problems = []
    for d in LOCKED_DOCS:
        p = ROOT / d
        if not p.exists():
            problems.append(f"  ✗ {d} — 파일 없음")
            continue
        code, out, _ = _git("log", "--oneline", "-1", "--", d)
        if code != 0 or not out.strip():
            problems.append(f"  ✗ {d} — git에 커밋된 적 없음 (백업 안 됨, 수정해도 흔적 없음)")
            continue
        code, out, _ = _git("diff", "--stat", "HEAD", "--", d)
        if out.strip():
            problems.append(f"  ✗ {d} — 커밋본과 다름 (커밋 후 수정됨)")
    if problems:
        refuse("사전확정 문서 상태 이상:\n" + "\n".join(problems) +
               "\n\n조치: 의도한 수정이면 커밋하고 다시 실행. "
               "의도치 않은 수정이면 git diff로 확인 후 되돌릴 것.\n"
               "결과를 본 뒤 기준을 바꾸는 것을 막기 위한 장치이므로 이 검사를 우회하지 마십시오.")
    print("✓ 사전확정 문서 3종 무결 (git 커밋본과 일치)")
    for d in LOCKED_DOCS:
        _, out, _ = _git("log", "--format=%h %ad", "--date=short", "-1", "--", d)
        print(f"    {d}: {out.strip()}")


def wilson_lower(wins, n, z=1.96):
    if n == 0:
        return 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - m) * 100


def bootstrap_ci(sample, iters=4000, seed=20260820):
    if not sample:
        return 0.0, 0.0
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choices(sample, k=len(sample))) / len(sample) for _ in range(iters))
    return means[int(iters * 0.025)], means[int(iters * 0.975)]


def load():
    """CSV(봇 기록)와 원장(거래소 실제)을 각각 로드. 원장은 건별 오염 여부도 표시."""
    if not TRADES.exists():
        refuse(f"{TRADES} 없음")
    csv_rows = [r for r in csv.DictReader(open(TRADES, encoding="utf-8")) if r.get("exit_time")]
    csv_rows.sort(key=lambda r: r["exit_time"])

    led_rows = []
    if LEDGER.exists():
        led_rows = list(csv.DictReader(open(LEDGER, encoding="utf-8")))
        led_rows.sort(key=lambda r: r["exit_time"])
    return csv_rows, led_rows


def find_contaminated(led):
    """원장 건별 오염 탐지 — ledger_reconcile이 시간창(exit+12h)으로 매칭하는데,
    같은 코인을 그 안에 다시 거래하면 앞 거래가 뒷 거래 손익까지 흡수한다.
    총합은 맞지만 건별 값은 틀린다(2026-08-20 발견, 8쌍 14건)."""
    def t(s):
        return datetime.fromisoformat(s).astimezone(KST)
    pairs = []
    for i, a in enumerate(led):
        for j in range(i + 1, len(led)):
            b = led[j]
            if b["symbol"] != a["symbol"]:
                continue
            if t(b["entry_time"]) <= t(a["exit_time"]) + timedelta(hours=12):
                pairs.append((i, j))
                break
    return pairs


def pct_of_margin(r, pnl_field):
    m = float(r.get("margin_usdt") or 30)
    return float(r.get(pnl_field) or 0) / m * 100 if m else 0.0


def main():
    print("=" * 68)
    print(f"51건 관문 / 존속 판정 계산기   실행 {datetime.now(KST):%Y-%m-%d %H:%M} KST")
    print("=" * 68)
    check_preconditions()

    csv_rows, led_rows = load()
    n_csv = len(csv_rows)
    print(f"\n거래 기록: CSV {n_csv}건" + (f" / 원장대조 {len(led_rows)}건" if led_rows else " / 원장 없음"))

    if n_csv < TARGET_N:
        print(f"\n※ 아직 {TARGET_N}건 미달 ({TARGET_N - n_csv}건 남음). 아래는 현재 시점 중간값입니다.")

    # ---- 잣대별 표본 구성 -------------------------------------------------
    # 원본 = exit_time 있는 전체 / 버그조정 = 증거금 대비 -100% 초과 제외
    csv_all = [pct_of_margin(r, "pnl_usdt") for r in csv_rows]
    csv_adj = [x for x in csv_all if x > OUTLIER_PCT]
    outliers = [(r["symbol"], pct_of_margin(r, "pnl_usdt"), r["exit_time"][:16])
                for r in csv_rows if pct_of_margin(r, "pnl_usdt") <= OUTLIER_PCT]

    print(f"\n[표본 정의 — docs/51GATE_UNITS.md 고정]")
    print(f"  원본     {len(csv_all)}건")
    print(f"  버그조정 {len(csv_adj)}건 (이상치 = 증거금 대비 {OUTLIER_PCT:.0f}% 초과 손실)")
    for s, v, t_ in outliers:
        print(f"    제외: {s:<12}{v:>+8.1f}%  {t_}")

    # ---- 기준1: 킬스위치 ---------------------------------------------------
    print(f"\n{'─'*68}\n[기준1] 킬스위치 — Wilson 95% CI 하한 ≥ {GATE1_MIN_LOWER}%")
    g1 = {}
    for label, rows_, field in (("CSV", csv_rows, "pnl_usdt"),
                                ("원장", led_rows, "net_pnl_usdt")):
        if not rows_:
            continue
        w = sum(1 for r in rows_ if float(r.get(field) or 0) > 0)
        lo = wilson_lower(w, len(rows_))
        g1[label] = lo >= GATE1_MIN_LOWER
        print(f"  {label:<4} 승 {w}/{len(rows_)} = {w/len(rows_)*100:.1f}%, 하한 {lo:.1f}%"
              f"  → {'충족' if g1[label] else '미충족'}")
    # 판정력 확인: 남은 거래가 전패해도 통과하는가
    if n_csv < TARGET_N:
        w = sum(1 for r in csv_rows if float(r.get("pnl_usdt") or 0) > 0)
        worst = wilson_lower(w, TARGET_N)
        if worst >= GATE1_MIN_LOWER:
            print(f"  ⚠ 남은 {TARGET_N-n_csv}건 전패해도 하한 {worst:.1f}% — "
                  f"이 기준은 이미 통과가 확정돼 판정력이 없습니다(무료 1점)")

    # ---- 기준2: 건당EV (여기가 2026-08-20 사고 지점) -------------------------
    print(f"\n{'─'*68}\n[기준2] 건당 기대값 — 39건 시점 기준값보다 개선/유지")
    print(f"  ※ 단위는 USDT 절대액입니다(%가 아님). 2026-08-20 오독 사고 지점.")
    g2 = {}
    for label, rows_, field in (("CSV", csv_rows, "pnl_usdt"),
                                ("원장", led_rows, "net_pnl_usdt")):
        if not rows_:
            continue
        base_rows = rows_[:GATE2_BASELINE_N]
        base_v = sum(float(r.get(field) or 0) for r in base_rows) / len(base_rows)
        cur_v = sum(float(r.get(field) or 0) for r in rows_) / len(rows_)
        base = Metric(base_v, "USDT", label, f"{GATE2_BASELINE_N}건")
        cur = Metric(cur_v, "USDT", label, f"{GATE2_BASELINE_N}건")   # 비교 축을 같게
        g2[label] = cur >= base
        print(f"  {label:<4} {base.value:+.3f} → {cur.value:+.3f} USDT/건"
              f"  → {'충족' if g2[label] else '미충족'}")
    print(f"  참고: 문서 기재 기준값 {GATE2_BASELINE_USDT:+.3f} (CSV 잣대)")
    print(f"  ⚠ 원문 설계 약점 — 건당 증거금이 50→20→25→30으로 변해와 절대액 비교임"
          f"(사이즈 커지면 통과 쉬워짐). 기준은 바꾸지 않고 명기만 함.")

    # 잣대 혼용이 실제로 막히는지 실증
    try:
        if led_rows:
            a = Metric(0.0, "USDT", "원장", "46건")
            b = Metric(GATE2_BASELINE_USDT, "USDT", "CSV", "39건")
            _ = a >= b
            print("  ✗ 경고: 잣대 혼용이 막히지 않았습니다 — 코드 점검 필요")
    except UnitMismatch:
        print("  ✓ 잣대 혼용 차단 작동 확인 (원장값 vs CSV기준값 비교 시 예외)")

    # ---- 기준3: 인프라 이상치 ----------------------------------------------
    # 원문 "HFT/HEI급 체결지연·버그로 인한 이상치 손실 없음"이 두 가지로 읽힌다.
    # 결과를 보고 유리한 쪽을 고르는 것을 막기 위해 둘 다 출력하고, 갈리면 미충족으로 센다
    # (docs/51GATE_UNITS.md 기준3 절에서 결과 보기 전에 고정한 규칙).
    print(f"\n{'─'*68}\n[기준3] 인프라 이상치 — 해석 2가지 병기, 갈리면 미충족 처리")
    known = {"HFTUSDT", "HEIUSDT"}          # 원문이 예시로 명시한 두 사건
    a_ok = len(outliers) == 0                                    # 해석A: 표본에 있는가
    new_out = [o for o in outliers if o[0] not in known]
    b_ok = len(new_out) == 0                                     # 해석B: 신규 발생했는가
    print(f"  해석A(문자 그대로: 표본 내 존재 여부)  이상치 {len(outliers)}건"
          f" → {'충족' if a_ok else '미충족'}")
    print(f"  해석B(신규 발생 기준: HFT/HEI 외)      신규 {len(new_out)}건"
          f" → {'충족' if b_ok else '미충족'}")
    g3 = a_ok and b_ok
    if a_ok != b_ok:
        print(f"  ⚠ 두 해석이 갈림 → 보수적으로 **미충족** 처리. "
              f"이 기준은 판정력이 없었습니다(원문 결함).")

    # ---- 기준4: 캡150 세그먼트 ---------------------------------------------
    print(f"\n{'─'*68}\n[기준4] 캡150 세그먼트 승률 — 전체 대비 {GATE4_MAX_GAP_PP}%p 이상 안 낮으면 충족")
    g4 = {}
    for label, rows_, field in (("CSV", csv_rows, "pnl_usdt"),
                                ("원장", led_rows, "net_pnl_usdt")):
        if not rows_:
            continue
        base_w = sum(1 for r in rows_ if float(r.get(field) or 0) > 0) / len(rows_) * 100
        for basis, cut, tf in (("문서(exit)", GATE4_CUTOFF, "exit_time"),
                               ("병기(entry)", GATE4_CUTOFF_REAL, "entry_time")):
            seg = [r for r in rows_
                   if datetime.fromisoformat(r[tf]).astimezone(KST) >= cut]
            if not seg:
                print(f"  {label:<4} {basis:<12} 해당 거래 없음")
                continue
            sw = sum(1 for r in seg if float(r.get(field) or 0) > 0) / len(seg) * 100
            ok = sw >= base_w - GATE4_MAX_GAP_PP
            if basis.startswith("문서"):
                g4[label] = ok
            print(f"  {label:<4} {basis:<12} n={len(seg):>2} 승률 {sw:5.1f}% "
                  f"(전체 {base_w:.1f}%) → {'충족' if ok else '미충족'}")

    # ---- 종합 --------------------------------------------------------------
    print(f"\n{'='*68}\n판정 (공식 = CSV 잣대, 사전확정 문서 지시)")
    off = [("기준1", g1.get("CSV")), ("기준2", g2.get("CSV")),
           ("기준3", g3), ("기준4", g4.get("CSV"))]
    met = sum(1 for _, v in off if v)
    for k, v in off:
        print(f"  {k}: {'충족' if v else '미충족'}")
    verdict = "통과" if met >= 3 else "보류"
    if not g1.get("CSV"):
        verdict = "미통과(킬스위치 단독 위반)"
    print(f"  → {met}/4 충족 = **{verdict}**")
    if n_csv < TARGET_N:
        print(f"  (※ {TARGET_N}건 미달 상태의 중간 계산이며 확정 판정이 아님)")

    if led_rows:
        led_off = [g1.get("원장"), g2.get("원장"), g3, g4.get("원장")]
        print(f"\n병기 (원장 잣대): {sum(1 for v in led_off if v)}/4 충족")

    # ---- 원장 건별 오염 경고 ------------------------------------------------
    if led_rows:
        pairs = find_contaminated(led_rows)
        if pairs:
            print(f"\n{'─'*68}\n⚠ 원장 건별 값 오염 {len(pairs)}쌍 감지")
            print("  같은 코인을 12시간 내 재거래하면 ledger_reconcile의 시간창 매칭이")
            print("  앞 거래에 뒷 거래 손익까지 귀속시킵니다. 총합은 맞지만 건별은 틀립니다.")
            zeros = [r for r in led_rows if abs(float(r["net_pnl_usdt"])) < 1e-9]
            print(f"  net=0.000으로 찍힌 {len(zeros)}건은 '손익 0'이 아니라 매칭 실패입니다"
                  f" → 승률 계산에서 패배로 세어져 원장 승률이 과소평가됩니다.")
            # 쌍 합침 보정
            skip = {i for p in pairs for i in p}
            merged = [(float(led_rows[i]["net_pnl_usdt"]) + float(led_rows[j]["net_pnl_usdt"]))
                      / (float(led_rows[i]["margin_usdt"]) + float(led_rows[j]["margin_usdt"])) * 100
                      for i, j in pairs]
            rest = [pct_of_margin(r, "net_pnl_usdt") for k, r in enumerate(led_rows) if k not in skip]
            fixed = [x for x in rest + merged if x > OUTLIER_PCT]
            raw = [pct_of_margin(r, "net_pnl_usdt") for r in led_rows
                   if pct_of_margin(r, "net_pnl_usdt") > OUTLIER_PCT]
            print(f"  보정 전 EV {sum(raw)/len(raw):+.2f}% (n={len(raw)}) → "
                  f"쌍 합침 후 {sum(fixed)/len(fixed):+.2f}% (n={len(fixed)})")
            print("  → orderId 기반 매칭으로 교체 전까지 건별 원장값을 근거로 쓰지 마십시오.")

    # ---- 9/19 존속 판정 지표 ------------------------------------------------
    if led_rows:
        print(f"\n{'─'*68}\n[9/19 존속 판정 지표] — 원장 잣대, 버그조정 표본")
        pairs = find_contaminated(led_rows)
        skip = {i for p in pairs for i in p}
        merged = [(float(led_rows[i]["net_pnl_usdt"]) + float(led_rows[j]["net_pnl_usdt"]))
                  / (float(led_rows[i]["margin_usdt"]) + float(led_rows[j]["margin_usdt"])) * 100
                  for i, j in pairs]
        rest = [pct_of_margin(r, "net_pnl_usdt") for k, r in enumerate(led_rows) if k not in skip]
        s = [x for x in rest + merged if x > OUTLIER_PCT]
        ev = sum(s) / len(s)
        lo, hi = bootstrap_ci(s)
        print(f"  건당 EV {ev:+.2f}% (증거금 대비, 단순평균), n={len(s)}")
        print(f"  부트스트랩 95% CI [{lo:+.2f}%, {hi:+.2f}%]")
        if lo > 0:
            d = "통과 — 자본 사다리 진행(단, 상관상한 구현 후)"
        elif ev >= 5:
            d = "보류 — 3차 마감일 정하고 계속(단 1회만)"
        else:
            d = "중단 검토 — 실거래 정지 여부를 그 자리에서 결정"
        print(f"  → DEADLINES.md 기준: **{d}**")
        print(f"  (2026-09-19 이전에는 참고값. 확정 판정은 그날 이 스크립트 출력으로 함)")

    print(f"\n{'='*68}")
    print("이 출력을 그대로 판정문에 붙이십시오. 숫자를 손으로 옮겨적지 마십시오.")
    print("=" * 68)


if __name__ == "__main__":
    main()
