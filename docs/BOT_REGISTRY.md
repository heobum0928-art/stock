# 봇 등록부 — 무엇이 실제 돈을 쓰는가 (2026-08-29 갱신)

**이 문서가 필요한 이유**: 2026-08-20 감사에서 **파일 이름·주석과 실제가 다른 사례 2건**이
발견됐다. 이름만 보고 "모의니까 괜찮다"고 판단하면 실제 돈이 나가는 상태였다.

| 파일 | 이름/주석이 말한 것 | 실제 |
|---|---|---|
| `rsi_extreme_short_paper.py` | 이름에 **paper**(모의) | 2026-07-13부터 **실거래**였음 (08-19 disarm) |
| `core_leveraged.py` | "100% 모의, 절대 실거래 안 나감" | **실거래 중** — 08-20 08:43 실주문 체결 |

**파일명은 바꾸지 않는다.** import 경로(`tg_bot.py`가 `margin_manual_long_trader`를 직접
import), watchdog 등록 37곳, 스케줄러 작업 11개가 경로에 묶여 있어 개명이 더 큰 사고를
낸다. 대신 **이 문서를 단일 진실 공급원으로 삼는다.**

---

## 🔴 실거래 — 실제 돈이 나감

| 봇 | 방향 | 엔진명 | 캡 | 서버측 손절 | 비고 |
|---|---|---|---|---|---|
| `margin_short_trader.py` | 숏 | `mshort_fut`(선물) | **350 USDT** | **있음** | **58건 완료**, 51건 관문 **통과**(2026-08-28 `gate_eval.py` 3/4 충족). 파라미터 동결 중. 진입 7h+30~40% |
| `margin_short_trader.py` | 숏 | `mshort`(마진) | 100 USDT | **있음**(2026-08-24 추가) | 마진대출 가능 코인만. 08-20에 캡이 540으로 자동상향돼 있던 것 원복 |
| `margin_short_wide_trader.py` | 숏 | `mshort_wide_fut`(선물) | **350 USDT** | **있음** | ★2026-08-25 신설. **진입완화판**(7h+15~30%), 청산은 원본과 동일. 21건 완료 |
| `margin_short_wide_trader.py` | 숏 | `mshort_wide`(마진) | 100 USDT | **있음**(임시스탑 폴백 포함) | 위와 같은 봇의 마진 경로 |
| `core_leveraged.py` | **롱** | `core_lev` | 100 USDT | **없음** | BTC 2배. 주석이 "모의"라 적혀 있었으나 실거래. SMA50↑→SCOUT30% / SMA200↑→FULL100% |
| `tg_bot.py` | 롱(간접) | `manuallong` | 0 USDT | 해당없음 | 재량롱 청산·트레일링을 실제로 돌리는 유일한 프로세스 |

**⚠️ `core_lev`(BTC 롱)에는 서버측 손절이 없다.** 봇이 죽어 있는 동안 가격이 급변하면
보호 장치가 없다. 숏 4경로는 2026-08-24 이후 전부 서버측 스탑을 건다 — 선물은
`/fapi/v1/algoOrder`(algoType=CONDITIONAL, **구 `/fapi/v1/order` 조회로는 안 보인다**),
마진은 `/sapi/v1/margin/order` STOP_LOSS. 마진 숏은 손절가가 현재가에서 너무 멀면
거래소 가격필터에 막혀 **임시(provisional) 스탑**을 먼저 걸고 나중에 정식으로 교체한다.

> **2026-08-29 캡 변경(사용자 직접 수정, 2회)**:
> - 선물(`binance_live_config.json`): `mshort_fut` 250→**350**, `mshort_wide_fut` 250→**350**.
>   건당 30이므로 봇당 약 11건까지. `daily_loss_limit_usdt` 100은 그대로.
> - 마진(`margin_live_config.json`): `mshort_wide` 100→**200**(건당 50이므로 2건→**4건**),
>   그리고 같은 날 2차 수정으로 **`daily_loss_limit_usdt` 45→100**. `rsishort` 30→50도
>   같이 올렸으나 그 엔진은 2026-08-20 중단(watchdog 제거·armed 아님)이라 무효과다.
>
> **선물은 캡만 올렸고(손실한도 100 유지), 마진은 캡과 손실한도를 둘 다 올렸다.**
> 2026-08-16에 AI 3개가 "캡 확대(기대EV)와 손실한도 확대(꼬리위험)는 별개 결정인데
> 하나로 묶었다"고 지적한 사안 — 마진 쪽은 사용자가 그 설명을 듣고 의도적으로 둘 다 올렸다.
> 이유: 마진은 손절 1건이 -40(50×2×40%)이라 한도 45에서는 **첫 손절에 그날이 끝나** 캡을
> 4건으로 늘려도 의미가 없었다. 한도 100이면 2건까지 버틴다.
> 선물은 손절 1건 약 -24라 4건이면 -96으로 한도 100에 닿는다.
>
> **3차 수정(같은 날) — 건당 사이즈 확대**: `FUT_MARGIN_PER_TRADE` **30→50**
> (코드 상수, `margin_short_trader.py`·`margin_short_wide_trader.py` 양쪽. **설정파일이
> 아니므로 봇 재시작이 필요하다** — 캡·한도는 자동 반영이지만 이건 아니다).
> 손절 1건 손실이 **-24 → -40 USDT**가 되므로 선물 `daily_loss_limit_usdt`도
> **100→200** 함께 상향. 08-16 원칙("캡 확대와 한도 확대는 별개 결정")의 예외로 취급한
> 이유: 이번엔 캡이 아니라 **건당 손실액 자체**를 바꾼 것이라, 한도를 안 올리면 손절
> 2.5건에 하루가 끝나 확대 효과가 사라진다(사용자에게 설명 후 확답 받음).
> 엔진캡 350 기준 동시 **11건 → 7건**.
>
> **양쪽 하루 최대손실 합계: 145 → 200 → 최종 300 USDT**(선물 200 + 마진 100).
> 두 파일이 별도 카운터이므로 계정 전체로는 이 둘의 합이 실질 한도다.
> 하루에 이 금액이 나갈 수 있다는 뜻이며, 지갑(~1,550)의 약 19%다.
>
> `global_cap_usdt`는 선물 280 / 마진 680 그대로인데 개별 캡 합계는 선물 830 / 마진 440이
> 되어 원래 관례("global = 개별 합계")와 어긋난다. 다만 아래 버그 때문에 global_cap은
> 실제로 작동하지 않으므로 지금은 무해하다 — **버그를 고치는 순간 이 값이 실제 상한이 되니
> 그때 같이 맞춰야 한다.**

**자본 분리**: `data/binance_live_config.json`(선물, 일일손실한도 100, 전체상한 280) /
`data/margin_live_config.json`(마진, 일일손실한도 **100**, 전체상한 680). 두 파일이 별도라
계정 실질 일일손실한도는 합계 **200 USDT**다(2026-08-29 마진 45→100 상향 반영).

> ⚠️ **알려진 버그**: 일일손실한도는 **엔진별이 아니라 파일별로 공유**된다
> (`binance_guard.STATE` = `data/binance_live_state.json` 하나를 `core_lev`·`mshort_fut`·
> `mshort_wide_fut` 셋이 같이 쓴다). 한 엔진이 손실을 내면 나머지 둘도 같이 막힌다.
> 미수정 — `docs/SESSION_HANDOFF.md` 5항.

### ⚠️ 설정 파일이 둘로 나뉘어 있다 — 2026-08-22 실제 사고

한쪽만 보고 "실거래 봇이 뭐뭐인지"를 판단하면 틀린다. 2026-08-22에 AI가
`margin_live_config.json`만 확인하고 "armed = mshort, manuallong"이라고 보고했는데,
`binance_live_config.json`에 별도로 armed된 **`core_lev`가 통째로 누락**됐다. 그 결과
"계좌에 여윳돈이 없다"는 잘못된 진단을 했고, BTC 롱 포지션 0.003개(명목 220 USDT)가
열려 있는 것도 못 봤다. 사용자가 "보유 포지션은 없어?"라고 직접 물어서야 발견됐다.

**규칙: armed 엔진을 확인할 때는 반드시 두 파일을 모두 읽는다.** 한 줄 명령:
```bash
python -c "import json,glob;[print(f, json.load(open(f,encoding='utf-8')).get('armed_engines')) for f in glob.glob('data/*live_config*.json')]"
```
그리고 **설정 파일이 아니라 거래소 API로 실제 포지션을 조회**하는 것이 유일한 확인 방법이다
(`/fapi/v2/positionRisk`). 봇의 `*_pos.json`은 그 봇이 아는 것만 담는다 — 위 BTC 롱은
어떤 `*_pos.json`에도 없었다.

### 현재 실거래 상태 스냅샷 (2026-08-29 00시 KST)

- **실제 돈을 쓰는 봇은 3개**: `margin_short_trader.py`(숏), `margin_short_wide_trader.py`
  (숏·진입완화), `core_leveraged.py`(롱)
- armed: 선물 `['core_lev','mshort_fut','mshort_wide_fut']` / 마진 `['mshort','manuallong','mshort_wide']`
- 선물계좌 잔고 1,549 USDT / 가용 1,269 USDT. 마진레벨 2.25(1.3 밑이 위험)
- 열린 선물 포지션 8건: BTC 롱 0.003(진입 73,268.67) + 숏 7건(CHIP·MANTRA·BEAMX·MOVR·
  EDEN·BMT·PROM). 마진 대출숏 다수(TRUMP·VET 등 — 일부는 과거 잔여분)
- 프로세스 중복처럼 보이는 것은 정상 — `watchdog.py`가 띄우고 각 봇이 자식을 하나 더 만드는
  런처 패턴이다(부모/자식 확인 완료). 중복 주문 위험 아님.

> **이 스냅샷은 금방 낡는다.** 판단에 쓸 때는 반드시 거래소 API로 다시 조회한다.
> 봇의 `*_pos.json`은 그 봇이 아는 것만 담는다. **선물(`/fapi/v2/positionRisk`)만 보면
> 마진 포지션을 통째로 놓친다** — 2026-08-28에 실제로 TRUMP 마진숏을 빠뜨린 보고를 했고
> 사용자가 "TRUMP도 있는 거 같던데"로 잡아냈다. 마진은
> `/sapi/v1/margin/account`의 `borrowed > 0`으로 확인한다.

---

## 🟡 모의 — 주문 API 미호출

| 봇 | 방향 | 목적 | 표본(2026-08-29) | 마감일 |
|---|---|---|---|---|
| `shadow_fleet.py` | 숏 | 청산규칙 6변형 짝비교 (V0~V5) | 226행 / 신호 48개 | 9/2 |
| `bc_rule_shadow_paper.py` | 숏 | 실전 진입 미러링 + 손실축소 규칙 | 20건(목표 20 도달) | 9/2 |
| `oi_divergence_short_paper.py` | 숏 | OI 다이버전스 필터 | 12건 | 9/2 |
| `alt_momentum_long_paper.py` | **롱** | 알트 모멘텀 Top3 (100건 목표) | 20건 | 10월 중순 |
| `quietpump_long_paper.py` | **롱** | ★2026-08-26 신설. 조용한급등 — 봉인검정 7기준 전부 통과한 첫 후보. 신호 1건마다 무작위 대조군 1건 동시 진입 | 40행 / 20쌍(목표 60쌍) | **9/19 소량파일럿 체크포인트 / 10/26 완전판정** |

앞 4개는 `docs/DEADLINES.md` 1차 마감(2026-09-02) 판정 대상이다. **마감 전에 중단하거나
규칙을 바꾸지 않는다.** quietpump는 `docs/PREREG_QUIETPUMP_LONG.md`가 별도 마감을 정한다.

> ⚠️ **quietpump 보유기간 24h로 확정 (2026-08-29, 사용자 결정)**: 사전등록·봉인검정은
> 48시간인데 코드(`quietpump_long_paper.py:66`)는 처음부터 `HOLD_H = 24`였다. 48h로
> 되돌리면 표본이 절반 속도라 사용자가 24h 유지를 선택했고, 문서를 코드에 맞췄다.
> **대가: 이 봇은 더 이상 "봉인검정을 통과한 후보"가 아니다** — 그 수치(+3.522%,
> p=0.004)는 48h판의 것이고 24h판 홀드아웃은 계산된 적이 없다. 60쌍 판정은 백테스트
> 뒷받침 없는 단독 검정이 된다. 상세·금지사항은 `docs/PREREG_QUIETPUMP_LONG.md` 부칙.

---

## ⚪ 순수 로깅 — 매매 0, 데이터만 수집

| 봇 | 산출물 | 앞으로 답할 수 있는 질문 |
|---|---|---|
| `breadth_monitor.py` | `breadth_events.csv` (0.7MB) | 시장 쏠림과 성과의 관계 — 08-20 상관리스크 분석에 실사용됨 |
| `orderflow_logger.py` | `orderflow_events.csv` (88MB) | 급등 직전 매수압력이 선행하는가 (사후 재구성 불가) |
| `crossex_logger.py` | `crossex_events.csv` (2.5MB) | 거래소 간 선행 관계 (재구성 불가) |
| `volume_radar.py` | `volume_radar_events.csv` (1.5MB) | 급증 순간 호가 깊이 (재구성 불가) |
| `futures_logger.py` | `futures_signals.csv` (60MB) | 펀딩비·OI — **공식 히스토리 API로 대체 가능한지 확인 필요** |
| `upbit_notice_monitor.py` | `upbit_notice_events.csv` | 상장공지 감지지연 |
| `binance_notice_monitor.py` | `binance_notice_events.csv` | 상장공지 감지지연 |
| `coinpan_monitor.py` | `coinpan_posts.csv` | **커뮤니티 심리** — 손익인증 글 폭증이 꼭지인가, 종목 언급 급증이 선행하는가. ★2026-08-27 신설. **매매·알림 일절 없음.** 검정은 사전등록(`docs/PREREG_*.md`) 후에만 한다 |

## 🔵 판단 보류

| 봇 | 왜 보류인가 |
|---|---|
| `core_trader.py` | 무레버리지 BTC 벤치마크. core_leveraged 존폐가 정해질 때 같이 결정 |

---

## ⏸️ 2026-08-20 중단 — watchdog에서 제거됨 (파일은 보존)

무작위 대조군(`random_trades.csv` 46건 건당 -0.15%)이 기준선이다. **표본이 충분한데
무작위보다 나쁘거나 구분이 안 되면 계속 돌릴 이유가 없다.**

| 봇 | 표본 | 건당 | t | 사유 |
|---|---|---|---|---|
| `em_trader.py` | 411 | -0.53% | -2.31 | 무작위보다 나쁨, 자기 게이트(t≥3.0) 정반대 실패 |
| `ml_trader.py` | 423 | +0.02% | +0.07 | 60일 쌓고 완전한 무 |
| `accum_trader.py` | 185 | -0.36% | -2.06 | 음수 확정 |
| `rsi_trader.py` | 77 | -0.76% | -2.12 | volaccum(기폐기) 동급 |
| `rsi_extreme_short_paper.py` | 58 | -0.02% | -0.04 | 무작위와 구분 불가 + 손절 규칙 부재 |
| `retest_trader.py` | 78 | +0.06% | — | 60일간 신규거래 0건 |
| `hybrid_trader.py` | 0 | — | — | 생애 거래 0건. alt_momentum_long_paper에 포섭됨 |
| `reaction_paper_trader.py` | 8 | -2.23% | — | 13일간 0건, 30건까지 4개월 |
| `igniter_alert.py` | — | — | — | 알림 100% 차단 + CSV 소비자 0 + 약속된 ML코드 없음 |
| `bithumb_notice_monitor.py` | — | — | — | 산출물 읽는 코드가 어디에도 없음 |
| `margin_manual_long_trader.py` | 3 | — | — | `__main__` 없어 프로세스가 뜬 적 없음(placebo). **파일은 tg_bot이 import하므로 삭제 금지** |

---

## 갱신 규칙

1. **arm/disarm하거나 캡을 바꾸면 이 문서를 같이 고친다.** 오늘 사고의 원인이 코드는
   바뀌었는데 설명이 안 바뀐 것이었다.
2. 새 봇을 watchdog에 등록할 때 이 표에 한 줄 추가한다. `docs/DEADLINES.md` 운용규칙 5에
   따라 **마감일도 같이 정한다.**
3. 파일명과 실제가 다르면 개명하지 말고 **해당 파일 docstring 맨 위에 정정을 적고 여기에도
   기록한다.**

---

## 📒 원장대조 (ledger_reconcile) — 2026-08-29 신설 등록

| | |
|---|---|
| 파일 | `scripts/ledger_reconcile.py` (읽기전용, GET만 — 주문 API 미호출) |
| 산출물 | `data/margin_short_ledger.csv` |
| 주기 | watchdog ONESHOT + **30분 간격**(`ONESHOT_MIN_INTERVAL_SEC`) |
| 소비자 | `tg_bot.py`의 `/달력` — 이 파일이 없으면 CSV로 폴백하고 화면에 경고를 띄운다 |

**왜 있는가**: 봇 거래 CSV(`margin_short_trades.csv`, `margin_short_wide_trades.csv`)의
`pnl_usdt`에는 **펀딩비·수수료가 없다**(CLAUDE.md 2항). 이 스크립트가 거래소 원장
(`/fapi/v1/income`)을 긁어 거래별로 매칭해 진짜 순손익을 만든다.

**2026-08-29 두 가지 수정** (사용자 "달력 합계가 이상한데"로 발견):
1. **완화봇이 빠져 있었다** — 원본 봇 58건만 대조하고 `margin_short_wide_trades.csv`
   28건은 아예 안 봤다. 두 CSV를 모두 읽도록 확장(86건).
2. **/달력이 이 원장을 쓰도록 변경** — 이전엔 CSV를 직접 읽어 펀딩비가 빠진 -11.26 USDT를
   보여줬다. 실제는 **-43.50 USDT**(펀딩비 671건 -51.49 포함). 32 USDT를 낙관적으로
   보고 있었다.

**남은 한계**: 마진(spot) 건은 선물 income 원장에 없다(펀딩비가 아니라 **대출이자**를 낸다).
현재 CSV값을 그대로 net으로 쓰므로 **그 행들은 이자만큼 여전히 낙관적**이다. 달력 하단에
이 사실을 명시한다. 이자까지 반영하려면 `/sapi/v1/margin/interestHistory` 연동이 필요하다.

> **이것이 "봇 하나 추가 시 갱신할 5곳"의 실증 사례다.** 완화봇을 08-25에 만들 때
> 워치독·포지션현황·달력은 갱신했지만 **원장대조를 놓쳤고**, 그 결과 나흘간 완화봇 거래의
> 펀딩비가 어디에도 반영되지 않았다. 새 봇을 만들 때 이 표에 소비자를 함께 적는다.
