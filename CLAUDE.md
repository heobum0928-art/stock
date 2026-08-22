# CLAUDE.md — 이 저장소에서 반드시 지킬 것

실제 돈이 걸린 트레이딩 프로젝트다. 아래는 **실제로 사고가 났던 항목만** 적는다.
일반론은 적지 않는다.

## 1. 실거래 봇 확인 — 설정 파일이 둘이다

`armed_engines`를 볼 때 **반드시 두 파일을 모두** 읽는다. 한쪽만 보면 실거래 봇을 통째로 놓친다.

```bash
python -c "import json,glob;[print(f, json.load(open(f,encoding='utf-8')).get('armed_engines')) for f in glob.glob('data/*live_config*.json')]"
```

- `data/margin_live_config.json` — 마진 계좌 (mshort, manuallong, ...)
- `data/binance_live_config.json` — 선물 계좌 (core_lev, mshort_fut, ...)

**실제 포지션은 설정이 아니라 거래소 API로 확인한다.** 봇의 `*_pos.json`은 그 봇이 아는
것만 담는다.

```python
import sys; sys.path.insert(0,'.')
from bithumb.binance_guard import _signed
r = _signed('GET','/fapi/v2/positionRisk')
```

> 2026-08-22 사고: `margin_live_config.json`만 보고 "armed=[mshort, manuallong]"이라
> 보고 → `core_lev`(BTC 롱, 실거래) 누락 → "여윳돈 없다"는 오진 + 열려 있던 포지션 미발견.
> 사용자가 직접 물어서야 발견됨. 단일 진실 공급원은 `docs/BOT_REGISTRY.md`.

## 2. 단위 — `pnl_pct`는 명목가 기준이다

증거금 기준은 **2배**다(레버리지 2배). 전 거래에서 `pnl_usdt/margin_usdt ÷ pnl_pct = 2.00`
으로 확인된다.

- 사전등록 이상치 제외 규칙 "증거금 대비 -100% 초과" = **`pnl_pct < -50` 제외**
- 원장의 `funding_usdt / margin_usdt`는 **이미 증거금 기준**이다. 2를 또 곱하지 말 것.

> 2026-08-22 사고 2회: (a) `-100`을 `pnl_pct`에 그대로 적용해 표본이 n=47이어야 하는데
> n=48이 됨 → 필요표본 116건이 222건으로 부풀고 결론이 바뀜. (b) 펀딩비를 2배로 또 환산.
> `docs/51GATE_UNITS.md`가 만들어진 계기가 바로 이 단위 오독이다.

**판단에 쓰는 숫자는 보고 전에 `scripts/gate_eval.py` 출력과 대조한다.** 내 계산과 다르면
내 계산을 먼저 의심한다.

## 3. A vs B 비교는 반드시 짝비교(head-to-head)

같은 신호를 받은 건끼리 대응표본으로 비교한다. **그룹 평균 비교로 결론 내지 않는다.**
각각을 기준선과 비교한 결과로 "A와 B가 다르다"고 말하지 않는다.

> 같은 오류가 3회 반복됨: 08-20 V3 설계결함 / 08-21 레짐필터 "손해" 오결론 /
> 08-22 손절 V5_stop30 vs V0_base. 마지막 건은 주변평균으로 "V5가 열위"였는데
> 짝비교하면 **V5가 +5.27%p 우위**로 부호가 뒤집혔다(우측검열 1건이 만든 착시).

## 4. 지표 하나로 결론 내지 않는다 — 중앙값은 꼬리를 못 담는다

이 전략은 **승률 69.5%인데 평균이 음수**다. 질 때 -95%씩 잃기 때문이다.
중앙값·승률만 보면 좋아 보이고, 평균·청산을 넣으면 뒤집힌다.

> 08-22: "중앙 +16.96%로 40%+ 구간이 가장 좋다"는 로그 근거가 재현은 됐으나,
> 청산 시뮬레이션을 넣자 -0.54%(p=0.85)로 무너짐. **백테스트에 청산 시뮬레이션이
> 없으면 그 숫자는 쓰지 않는다.**

## 5. 여러 기준을 시험해보고 통과하는 걸 고르지 않는다

> 08-22: 같은 48건에 평균/중앙값/승률 세 자를 대보고 통과한 둘을 보고 → 과적합.
> 사용자가 "아 과적합 아니야?"로 잡아냄. 새 판정 기준은 **통과 여부를 확인하기 전에**
> 통계적 근거만으로 정한다.

## 6. 매매 주문은 실행하지 않는다

가격 조회·백테스트·기록·설정 확인은 하되, **주문 실행과 종목 선정(투자 조언)은 하지 않는다.**
`armed_engines` 추가나 캡 증액 같은 실제 돈이 나가는 설정 변경도 임의로 하지 않는다.
사용자가 직접 한다.

## 7. 동결 규율

`docs/DEADLINES.md`와 `docs/51GATE_CRITERIA.md`의 사전확정 기준은 **결과를 보고 바꾸지
않는다.** 51건 관문은 통계적 목표가 아니라 반응적 과최적화를 막는 행동 훈련 장치다.
"이번만 예외" 요청이 와도 기준을 고치지 말고, 왜 그 기준이 있었는지를 먼저 확인한다.

## 8. 주요 문서

| 파일 | 역할 |
|---|---|
| `docs/BOT_REGISTRY.md` | 무엇이 실제 돈을 쓰는가 — **단일 진실 공급원** |
| `docs/DEADLINES.md` | 마감일·판정 기준 (부칙 3에 2026-08-22 프로토콜 정정) |
| `docs/51GATE_CRITERIA.md` / `51GATE_UNITS.md` | 51건 관문 판정 기준·표본 정의 |
| `docs/would_change_log.md` | 발견·정정 이력 (append-only) |
| `docs/CAPITAL_LADDER.md` | 자본 확대 사다리 |
| `scripts/gate_eval.py` | 판정 계산기 — 수작업 계산 대신 이걸 쓴다 |

## 9. 실행 환경

- Python은 `.venv/Scripts/python.exe`를 쓴다(시스템 python엔 `requests` 없음)
- 한글 출력이 깨지면 `PYTHONIOENCODING=utf-8`
- 봇 프로세스가 2개씩 보이는 것은 정상 — `watchdog.py`가 띄우고 각 봇이 자식을 하나 더
  만드는 런처 패턴이다. 중복 주문 아님(부모/자식 PID로 확인 가능).
