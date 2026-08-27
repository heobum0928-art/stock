# 봇 등록부 — 무엇이 실제 돈을 쓰는가 (2026-08-22 갱신)

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

| 봇 | 방향 | 엔진명 | 캡 | 서버측 손절 | 현재 포지션 | 비고 |
|---|---|---|---|---|---|---|
| `margin_short_trader.py` | 숏 | `mshort_fut`(선물) | 150 USDT | **있음** | 없음 | **49건 완료**, 51건 관문 대상. 파라미터 동결 중. 실거래 49건 **전부 이 경로**(선물 100%) |
| `margin_short_trader.py` | 숏 | `mshort`(마진) | 100 USDT | **없음** | 없음 | 실거래 0건. 08-20에 캡이 540으로 자동상향돼 있던 것 원복 |
| `core_leveraged.py` | **롱** | `core_lev` | 100 USDT | **없음** | **BTC 0.003 (명목 220 USDT)** | BTC 2배. 주석이 "모의"라 적혀 있었으나 실거래. SMA50↑→SCOUT30% / SMA200↑→FULL100% |
| `tg_bot.py` | 롱(간접) | `manuallong` | 0 USDT | 해당없음 | 없음 | 재량롱 청산·트레일링을 실제로 돌리는 유일한 프로세스 |

**⚠️ 서버측 손절이 없는 경로가 셋이다.** 봇이 죽어 있는 동안 가격이 급변하면 보호 장치가
없다. `mshort_fut`(선물폴백)만 진입 직후 거래소에 STOP_MARKET을 걸고 3회 재조회로 검증한다.

**자본 분리**: `data/binance_live_config.json`(선물, 일일손실한도 100) /
`data/margin_live_config.json`(마진, 일일손실한도 45). 두 파일이 별도라 계정 실질 한도는
합계 145 USDT다.

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

### 현재 실거래 상태 스냅샷 (2026-08-22 23시 KST)

- **실제 돈을 쓰는 봇은 2개**: `margin_short_trader.py`(숏), `core_leveraged.py`(롱)
- 선물계좌 잔고 1,571 USDT / 사용중 증거금 116 USDT / 가용 1,467 USDT
- 마진계좌 283 USDT
- 열린 포지션 1건: BTCUSDT 롱 0.003 (진입 73,268.67, 08-20·08-21 2회 분할매수)
- 프로세스 중복처럼 보이는 것은 정상 — `watchdog.py`가 띄우고 각 봇이 자식을 하나 더 만드는
  런처 패턴이다(부모/자식 확인 완료). 중복 주문 위험 아님.

---

## 🟡 모의 — 주문 API 미호출, 9/2 마감 판정 대상

| 봇 | 방향 | 목적 | 표본 |
|---|---|---|---|
| `shadow_fleet.py` | 숏 | 청산규칙 6변형 짝비교 (V0~V5) | 신호 6건 |
| `bc_rule_shadow_paper.py` | 숏 | 실전 진입 미러링 + 손실축소 규칙 | 10건 |
| `oi_divergence_short_paper.py` | 숏 | OI 다이버전스 필터 | 5건 |
| `alt_momentum_long_paper.py` | **롱** | 알트 모멘텀 Top3 (100건 목표) | 4건 |

넷 다 `docs/DEADLINES.md` 1차 마감(2026-09-02) 판정 대상이다. **마감 전에 중단하거나
규칙을 바꾸지 않는다.**

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
