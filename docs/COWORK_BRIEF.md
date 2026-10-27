# 협업 브리프 — 다른 AI/사람이 이 저장소 코드를 분석할 때 (2026-10-28)

## 0. 먼저 지킬 것 (실제 돈이 걸려 있음)
- **`config.yaml`(바이낸스 API 키)과 `.env`류는 절대 읽어서 외부 AI에 보내지 않는다.** 이 문서와 코드만 공유한다.
- **주문 실행 금지.** `data/*live_config*.json`의 `armed_engines`·캡·레버리지·`max_total_short_notional_usdt` 변경 금지(사용자만 결정). 실거래 봇 파일(`scripts/margin_short*.py`, `scripts/core_leveraged.py`, `scripts/trend3_live.py`, `bithumb/*.py`)은 **읽기 전용 분석**만. 고칠 점은 "제안"으로 돌려준다.
- 숫자를 인용할 때는 잣대를 같이 쓴다(명목가/증거금/자본 기준). 자세한 단위 규칙은 `CLAUDE.md` 2항.
- 단일 진실 공급원: `docs/BOT_REGISTRY.md`(무엇이 돈을 쓰는가), `docs/would_change_log.md`(발견·정정 이력, 하단이 최신), `docs/RESEARCH_SCORECARD.md`(실적 기준).

## 1. 지금 상태 (2026-10-28 08:50 점검)
- 선물 지갑 약 1,177 USDT. 실거래 롱 3개: 비트코인(1배, 명목 ~570, `core_lev`), 이더리움·솔라나(1배, 명목 ~150씩, `trend3`). 평가손익 합계 -18.8.
- 숏은 완화봇(`mshort_wide_fut`, 5배, 건당 증거금 40 → 손절 약 -10)만 켜져 있음. 10-22 이후 10건 -7.3 USDT. 원본 숏은 신규 진입 OFF.
- 손실 중지선: 기준(2026-10-21 12:24, 지갑 1,174.7) 이후 순손익 -100이면 새 숏 진입만 차단(`scripts/loss_stop_watch.py`). 현재 +2.46.
- 반년 결과: 숏은 합쳐서 본전~마이너스, 롱(200일선 추세)만 근거가 남음. 연구 약 61건 중 확정된 우위 없음.

## 2. 파일 지도
| 역할 | 파일 |
|---|---|
| 감시·재시작 | `scripts/watchdog.py` (예약 작업 `CoinbaseWatchdog`가 부팅 시 기동) |
| 거래소 주문 가드(공용 게이트) | `bithumb/binance_guard.py` (`_gate`, `open_short_futures`, `close_short_futures`, `rebalance_long`) |
| BTC 롱 | `scripts/core_leveraged.py` |
| ETH·SOL 롱 | `scripts/trend3_live.py` |
| 완화 숏 | `scripts/margin_short_wide_trader.py` |
| 중지선 | `scripts/loss_stop_watch.py` |
| 실적표 | `scripts/monthly_pnl.py`, `scripts/lev2_parallel.py` |
| 연구 계산 | `scripts/*_eval.py`, `scripts/tradfi_overnight.py`, `scripts/kr_*.py` |

## 3. 이 AI가 특히 봐 주면 좋은 것 (검토 요청)
1. **숏 펀딩비 무시:** 완화봇은 펀딩률이 크게 음수인 코인(숏이 내는 쪽)도 진입한다. MEW 숏은 평가 +21이었는데 4시간마다 약 -5 펀딩이 나갔다(펀딩률 -1.19%/4h). 진입 시 펀딩률 확인·보유 중 청산 규칙이 있어야 하는가? `binance_guard.open_short_futures` 주변과 봇의 진입 경로를 확인해 달라.
2. **core_lev 사이징 이력:** 목표를 가용잔고로 계산해 숏 증거금 사용에 따라 464↔1000을 오갔다(2026-10-21 `_wallet_usdt()`로 수정). 같은 종류의 입력 불안정이 다른 곳(`trend3_live.leg_margin`, `live_target_notional`)에 남았는지 확인.
3. **프로세스 수명:** 앱 세션에서 띄운 봇이 앱 재시작 때 같이 종료됨(2026-10-23 07:29). watchdog이 꺼져도 알림이 오지 않는다 — watchdog 자체 생존 감시나 하트비트가 필요한가?
4. **서버측 손절 없는 롱:** `core_lev`에는 거래소 서버측 STOP이 없다. 200일선 규칙의 청산은 봇이 살아 있어야 작동. 봇이 죽은 동안의 위험 대비책?
5. **설정 파일 파손:** JSON이 깨지면 `load_config()`가 fail-safe로 모든 봇을 OFF로 본다(2026-10-18 사고). 수정 전 검증/원자적 교체를 도구화할 수 있는가?
6. **일일 연구 루틴 멈춤:** `research-lab-daily`가 시작 20초 후 정지(2026-10-15~). 원인 후보: 앱 재시작, 승인 요청 대기. 스케줄러 쪽은 이 저장소 밖.

## 4. 분석 결과를 돌려줄 때의 형식
- 문제 → 근거(파일:줄) → 재현 방법 → 제안(코드는 **제안으로**) → 위험(실거래 영향).
- 수익 아이디어는 **사전등록 → 독립 기간 검증 → 비용 2배 → 체결 가능성** 순서. 과거 데이터에서 잘 맞는 규칙은 대부분 새 기간에서 무너졌다(통과 11건 중 거의 전부). 평균 한 숫자로 결론 내지 않는다(승률·꼬리·짝비교 병기).
- 이미 기각된 아이디어는 `docs/would_change_log.md`에서 먼저 검색해 중복을 피한다.
