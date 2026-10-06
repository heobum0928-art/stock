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
