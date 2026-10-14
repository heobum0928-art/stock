# 실거래 코드 감사 요약 (2026-10-02, 클라우드 루틴 "빗썸/바이낸스 봇 실전코드 일일 감사")

출처: 루틴 실행 로그의 요약(원본 보고서는 클라우드 임시 폴더라 저장소에 없음 — 사용자 앱에 파일 카드로 전달됨). 아래는 **로그에서 읽은 상위 발견 + 우리 로컬 코드로 재확인한 결과**다. 코드는 수정하지 않았다(실거래 봇은 사용자 결정).

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 1 | `margin_manual_long_trader.py`가 실행 중 `data/margin_live_config.json`의 `engine_caps_usdt`를 다시 쓴다(`_shift_cap_to_mshort`) — 사람 모르게 실거래 캡이 바뀔 수 있음(CLAUDE.md 6항과 충돌 소지) | **확인됨** — 함수 정의 `margin_manual_long_trader.py:45`(캡 재작성 :48), 호출 :339(수동 롱 청산 시 그 증거금을 mshort 캡으로 이동) |
| 2 | `margin_short_trader.py`·`margin_short_wide_trader.py`: 실제 숏을 열고 서버측 스탑을 건 뒤에도 포지션이 `POS_PATH`에 **루프가 끝날 때까지 저장되지 않음** — 중간 크래시 시 거래소엔 포지션이 있는데 봇은 모름(고아 포지션) | **확인됨(완화봇)** — `positions[sym]=` 기록 :1361·:1428, 같은 반복 내 저장 없이 `_save(POS_PATH, positions)`는 루프 후 :1451 |
| 3 | `newlisting_monitor.py`: `save_pos()`는 있으나 로드 함수 없음 — 재시작하면 보유 포지션 추적 소실 | 미확인(모의/실거래 여부 미확인) |
| 4 | 청산 함수가 실제 체결가를 반환하지 않아 `margin_short_trader`·`wide`·`rsi_extreme_short_paper`가 청산 전 조회가로 손익 계산(CLAUDE.md의 CSV 결함과 같은 계열) | 미확인 |
| 5 | MST와 MSWT의 `FUT_MARGIN_PER_TRADE`(120 vs 80) 불일치, 주석은 같다고 적혀 있음 | 미확인 |
| 6 | `rsi_trader`·`cascade_trader`·`accum_trader`: 시작 시 보유 코인 제외 목록 조회 실패가 조용히 삼켜짐(로그 없음) | 미확인 |

권장(사용자 결정): #2는 진입 직후 즉시 저장(`_save(POS_PATH, positions)`를 `positions[sym]=` 바로 뒤에)하는 한 줄 보강이 가장 값어치가 크다 — 실제 돈이 걸린 위험이며 구현 위험은 낮다. #1은 자동 캡 이동이 의도된 설계인지 사용자가 확인.

---

## 2026-10-05 추가 (클라우드 감사 10-04 실행분, 로컬 재확인)

이미 기록된 항목(#1 캡 자동 이동, #2 진입 직후 저장)은 중복 기재하지 않는다. 새로 확인한 것:

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 4 | 청산 함수가 체결가를 돌려주지 않아 손익이 주문 전 조회가로 계산됨 | **확인됨** — `margin_guard.py:436-439` `close_short()`는 `close_usdt`만, `binance_guard.py:610-612` `close_short_futures()`는 `{"live","result"}`뿐(가격 필드 없음). 진입 쪽만 체결가 반환으로 고쳐져 있음. 51건 관문 표본에 슬리피지만큼 체계 오차 가능(수정은 사용자 결정) |
| 3 | `newlisting_monitor.py` 재시작 시 포지션 소실 | **확인됨(코드 :67 `_positions = {}`, `load_pos` 없음)**. 단 `data/live_config.json`의 armed가 비어 있어 **실거래 아님**(모의 추적 한정) |
| 7 | `core_trader.py`가 `record_realized`를 부르지 않아 일일손실 관문 무력 | **확인됨(grep 0건)**. 단 같은 이유로 실거래 아님 → 영향 없음 |
| 8 | `margin_guard.py:433-435` 주문 예외 시 `log.error` 없이 원장만 기록, `:420` "대출수량 0" 반환은 로그·원장 모두 없음 | **확인됨** (선물 쪽 `binance_guard`는 로그를 남겨 비대칭) |
| 9 | `margin_short_wide_trader.py:662` `h or 0.0` — `get_held` 조회 실패(None)를 0으로 처리 | **확인됨**. 잔량을 크게 잡는 방향이라 "이미 청산" 오판은 아님 — 위험 낮음 |
| 5 | `FUT_MARGIN_PER_TRADE` 120 vs 80 | **확인됨**(`margin_short_trader.py:189`=120, `margin_short_wide_trader.py:205`=80). 의도된 차이인지 사용자 확인 |

코드는 수정하지 않았다.

---

## 2026-10-06 추가 (클라우드 감사 10-05 실행분, 로컬 재확인)

이미 기록된 항목(#1~#9)은 중복 기재하지 않는다. 로그 요약에서 읽힌 새 항목(원문은 일부 잘려 보임):

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 10 | `margin_guard.py` 보조 조회(`_price`·`_symbol_filters`·`_price_tick`)가 실패 시 로그 없이 0.0/기본값 반환, `_price`는 try/except 자체 없음 | **확인됨** — `margin_guard.py:143-167`. 호출부의 `price<=0` 검사로 대부분 완화(잔고 조회 버그 계열이지만 위험 낮음) |
| 11 | `binance_guard._mark_price`가 예외 시 로그 없이 0.0 반환 | **확인됨** — `binance_guard.py:205-213` |
| 12 | `binance_guard.rebalance_long`이 수량 단위를 `round(...,3)`(0.001)로 고정(거래소 조회 없음), `core_leveraged.MIN_QTY_STEP_BTC`와 숫자 중복 | **확인됨** — `binance_guard.py:380`. BTC 한정이라 현재 영향 없음, 한쪽만 바뀌면 어긋남 |

코드는 수정하지 않았다.

---

## 2026-10-08 추가 (클라우드 감사 10-07 실행분, 로컬 재확인)

#4(청산가 미반환)·#8~#12는 중복이라 생략. 새로 확인한 것:

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 13 | `margin_short_trader.py`의 `cancel_order`·`record_realized` 실패가 `except: pass`로 무로그 | **확인됨** — `:888-893`(외부청산 경로), `:1000`. 손익 누적·고아 스탑 정리가 조용히 빠질 수 있음(위험 중간, 수정은 사용자 결정) |
| 14 | `margin_manual_trader.py` `already_closed` 시 반환된 실제 체결가(`exit_price`)를 버리고 구시세 사용 | #4의 변형(수동 롱 봇 경로). 미수정 |
| 15 | `rsi_extreme_short_paper.py` 24h 조회 실패 시 필터 무력화·청산가 사전조회가 | **영향 없음** — `watchdog.py:224`에서 2026-08-20 제거, 현재 프로세스 없음 |

코드는 수정하지 않았다.

---

## 2026-10-09 추가 (클라우드 감사 10-08 실행분, 로컬 재확인)

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 16 | `core_trader.py:138-140`이 `live_rebalance()` 성공 여부와 무관하게 state를 덮어씀 | **확인됨(코드)**, 그러나 **영향 없음** — `data/live_config.json`의 `armed_engines`가 `[]`라 `core`는 실거래가 아니고 프로세스도 `--dry-run`. 실거래 BTC 롱은 `core_leveraged`(이미 수정됨). `core`를 arm할 때만 문제 |
| 17 | `margin_short_trader.py:165` `MARGIN_PER_TRADE=50.0`인데 이력 주석은 09-01에 100으로 끝남 | **확인됨(주석↔값 불일치)**. 08-15 주석은 "100→50으로 낮춤", 09-01 주석은 "50→100"인데 값은 50. 같은 파일의 `FUT_MARGIN_PER_TRADE=120.0`이 실제로 쓰이는 선물 경로 크기. 어느 쪽 의도인지는 사용자 확인 필요(코드 미수정) |
| 18 | 빗썸 현물 `manual/accum/cascade_trader`가 주문 전 호가를 진입가로 기록 | **영향 없음** — 빗썸 현물 `armed_engines=[]`(모의 전용) |

코드는 수정하지 않았다.

---

## 2026-10-10 추가 (클라우드 감사 10-09 실행분, 로컬 재확인)

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 19 | `margin_short_trader.py:1129`가 선물 청산 손익 계산에 `load_futures_config().get("leverage", 2)`를 씀. 10-08 커밋(41d9a9b)이 완화봇만 `engine_leverage(FUTURES_ENGINE)`로 바꿨다 | **확인됨(코드)**, 그러나 **지금은 영향 없음** — `binance_live_config.json`의 `leverage_by_engine`은 `{'mshort_wide_fut': 5}` 하나뿐이라 `mshort_fut`는 어느 쪽 함수로 읽어도 2배다. 원본봇은 신규진입도 꺼져 있다. 누가 `mshort_fut`를 `leverage_by_engine`에 넣는 순간부터 손익·일손실한도 집계가 어긋난다(잠재 위험, 수정은 사용자 결정) |
| 20 | `_load()`가 예외를 로그 없이 삼키고 기본값 반환(`margin_short_trader.py:351-353`, `margin_short_wide_trader.py:404-406`) | **확인됨** — 포지션 파일이 깨지면 "포지션 없음"으로 시작한다. 저장은 임시파일→교체(`_save`)라 깨질 확률은 낮다. 위험 낮음~중간 |
| 21 | `binance_guard._symbol_filters_futures`(`:289-301`)가 거래소정보 조회 실패 시 `(step 0.0, 최소주문 5.0)`을 정상값처럼 반환 | **확인됨** — #10(마진쪽 같은 계열)과 동일 패턴. 선물쪽은 호출부가 `qty<=0`을 막아 주문이 안 나가는 쪽이라 위험 낮음 |
| 22 | `margin_guard.get_margin_level` 실패 시 999.0(fail-open) | **의도된 설계**(`:252-266` 주석에 근거 명시, 실패는 `log.error`로 남김). 신규 위험 아님 |
| - | `rsi_extreme_short_paper.py` 이름과 달리 실주문 함수 호출 | 이미 #15에서 처리(2026-08-20 비활성화, `watchdog.py`에서 제거). 중복 |

코드는 수정하지 않았다.

---

## 2026-10-11 추가 (클라우드 감사 10-10 실행분, 로컬 재확인)

로그 요약이 중간에서 잘려(패턴 2 표까지만 보임) "새 발견" 본문은 확인하지 못했다. 보이는 부분만 재확인했다.

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 23 | `core_leveraged.py:69` `LEVERAGE = 2.0`이 하드코딩이고 설정(`binance_live_config.json`)을 읽지 않는다 | **확인됨(코드)**. 사이징(`:126,155,186,235`)이 전부 이 상수를 쓴다. 현재 설정 `leverage: 2`와 같아 **지금은 영향 없음**. 단 결정 대기 중인 "core_lev 1.5배"를 하려면 설정(`leverage_by_engine.core_lev`)만 바꿔서는 안 되고(거래소 레버리지는 정수, `binance_guard.engine_leverage`가 int) 이 상수를 바꿔야 한다 — 설정만 바꾸면 명목 크기는 그대로 2배다. 사용자 결정 시 함께 알릴 것 |

코드는 수정하지 않았다.

---

## 2026-10-13 추가 (클라우드 감사 10-12 실행분, 로컬 재확인)

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 24 | `newlisting_monitor.py`가 재시작 시 포지션을 디스크에서 복원하지 않음 | **확인됨(코드)**(`:67` `_positions = {}`, 저장만 있고 복원 함수 없음). **영향 없음** — `scripts/watchdog.py:252`에서 2026-07-13에 은퇴(프로세스 목록에도 없음), 빗썸 현물 `armed_engines=[]` |
| 25 | `bithumb/live_guard.execute_buy()`가 실체결가를 돌려주지 않음(margin/binance 가드는 이미 반영) | **확인됨(코드)** — 반환이 `{"live": True, "result": res}`뿐. **영향 없음** — 빗썸 현물 `armed_engines=[]`. #18과 같은 계열 |
| 26 | 3개 가드의 `load_config()`가 모든 예외를 로그 없이 삼키고 기본값 반환 | **확인됨**(`margin_guard.py:50`, `binance_guard.py:63`, `live_guard.py:52`). 단 기본값이 `enabled=False, armed_engines=[]`이고 docstring에 "FAIL-SAFE: 깨지면 OFF"로 명시된 **의도된 설계**(실거래가 꺼지는 안전한 쪽). 로그가 없어 "정상 OFF"와 "깨짐"이 구분 안 되는 점만 #20과 같은 계열의 관측성 문제 |
| - | `rsi_extreme_short_paper.py` 청산가를 체결가 대신 조회가로 씀(재무장 시 위험) | 이미 #15(2026-08-20 비활성화, watchdog 제거). 중복 |

코드는 수정하지 않았다.

---

## 2026-10-14 추가 (클라우드 감사 10-13 실행분, 로컬 재확인)

| # | 발견(루틴) | 로컬 재확인 |
|---|---|---|
| 27 | `margin_manual_trader.py:77-85`, `margin_manual_long_trader.py:95-103`(+`rsi_extreme_short_paper.py`)의 `_log_trade()`에 try/except가 없다. 청산 주문이 나간 뒤 CSV 기록이 실패하면(파일을 엑셀로 열어 둔 경우 등) 예외가 올라가 `del positions[coin]`·저장을 건너뛴다 | **확인됨(코드)**. 호출부 `tg_bot.py:485-495`가 예외를 잡아 봇이 죽지는 않지만, 같은 거래소 청산을 포지션이 남은 채로 다음 사이클에 다시 시도(`close_short`)하게 된다. **지금은 영향 없음** — `data/margin_manual_pos.json`·`margin_manual_long_pos.json`이 모두 `{}`(열린 재량 포지션 없음), `rsi_extreme_short_paper`는 #15로 비활성. `margin_short_trader`가 2026-08-20에 고친 패턴이 두 재량 도구에 포팅되지 않은 것 맞음 |
| 28 | `check_positions()`가 루프 끝에서 `_save_positions()`를 한 번만 호출(`margin_manual_trader.py:244-246`, `margin_manual_long_trader.py:346-347`) | **확인됨(코드)**. #27과 한 몸 — 루프 중 예외가 나면 앞서 처리한 청산 변경이 저장되지 않는다. 영향 조건과 현재 상태는 #27과 같다 |
| 29 | `margin_manual_long_trader._shift_cap_to_mshort()`가 실거래 캡을 코드가 자동 재배분(`margin_live_config.json` 직접 기록) | **확인됨(코드)**, 이미 기록된 결정 대기 항목(수동 롱 봇 캡 자동 변경이 의도된 설계인지). 새 위험 아님. `close_on_profit` 포지션이 이익 청산될 때만 발동하고 현재 재량 롱 포지션은 없다 |

수정하지 않았다(실거래 봇 코드는 이 루틴에서 건드리지 않음). #27·#28은 재량 포지션을 다시 열기 전에 고치면 된다.
