"""
Watchdog — keeps alt_monitor.py and tg_bot.py alive.
Restarts either process if it dies. Sends Telegram alert on restart.

Run: python scripts/watchdog.py
"""
import sys
import os
import atexit
import time
import subprocess
import logging
import requests
import yaml
import psutil
from pathlib import Path
from datetime import datetime, date, timezone, timedelta

KST = timezone(timedelta(hours=9))

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ★ 2026-08-17(watchdog 신뢰성 감사): logs/·data/ 디렉터리가 없으면 아래 FileHandler·LOCKFILE
# 쓰기가 즉시 크래시함 — 방어적으로 미리 생성(이미 있으면 no-op).
(ROOT / "logs").mkdir(parents=True, exist_ok=True)
(ROOT / "data").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WD][%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "logs" / "watchdog.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # 초마다 프로세스 확인

# ★ 2026-07-26: "죽었는지"만 보던 기존 감시(proc.poll())로는 못 잡는 문제 발견 — margin_short_trader가
#   같은 날 3번(3h34m/약5h/40분+) CPU delta=0으로 완전히 멈춰있었는데 프로세스 자체는 안 죽어서
#   (exit code 없음) 기존 로직이 전혀 감지 못했음. 그중 한 번(DEXE)은 손절 지연 슬리피지로 실제
#   손실(-2.3 USDT 추가분)까지 이어짐. CPU 누적시간이 일정 시간 이상 전혀 안 늘면 "행 상태"로 보고
#   강제 재시작하는 감시 추가.
# ★ 배포 전 에이전트 감사로 발견: 처음엔 전 봇 공통 30분 문턱을 쓰려 했는데, core_trader·core_leveraged
#   (CHECK_SEC=1800, 문턱과 완전히 같은 값이라 30초 폴링 양자화 오차로 경계에서 오탐 가능)와
#   hybrid_trader(CHECK_SEC=21600=6시간, 문턱보다 훨씬 길어서 매 사이클 확정적으로 "행상태"로
#   오판되어 30분마다 영구 킬-재시작 루프에 빠질 뻔함 — 셋 다 "일봉 신호라 폴링 느려도 됨" 계열
#   봇이라 자기 CHECK_SEC 자체가 김) — 봇별 자체 폴링주기를 감안해 개별 문턱을 두는 걸로 수정.
HANG_CHECK_SEC = 1800   # 기본값(대부분의 봇: margin_short_trader 300s·rsi_extreme_short_paper 300s
                        # ·accum_trader 30s 등 — 전부 이 문턱의 1/6 이하 주기라 안전)
HANG_CHECK_OVERRIDE_SEC = {
    # 일봉 신호 기반이라 폴링 자체가 느린 봇들 — 각자 CHECK_SEC의 약 3배로 여유를 둠
    "core_trader": 5400,        # CHECK_SEC=1800 × 3
    "core_leveraged": 5400,     # CHECK_SEC=1800 × 3 (실전봇이라 너무 길게는 안 둠)
    "hybrid_trader": 43200,     # CHECK_SEC=21600 × 2
    # ★ 2026-08-17(watchdog 신뢰성 감사, 사용자 확인 후 적용): margin_short_trader·accum_trader
    # 도 다른 실전봇들과 동일하게 30분 문턱을 못 넘겨 오탐 재시작 중이었음(logs/watchdog.log
    # 33.5시간 창에서 각 65회 확인) — 이 기능이 원래 잡으려던 진짜 행상태(2026-07-26 DEXE
    # 손절지연 손실 사고)에 대한 감지력은 유지하되 오탐만 줄이도록 core_trader/core_leveraged와
    # 같은 90분으로 절충(사용자가 "30분 유지" 대신 이 옵션 선택, 2026-08-17).
    # ★ 2026-08-25: 90분(5400s)으로도 오탐 재현 확인(watchdog.log 05:43~12:11, 90분 간격
    #   반복). 원인은 bc_rule_shadow_paper·oi_divergence_short_paper와 완전히 동일한 구조적
    #   문제(I/O바운드 경량폴링이라 CPU기반 행감지가 안 맞음) — 그래서 그 둘과 같은 6시간으로
    #   맞춘다. 2026-08-17엔 "실전봇이라 사용자 확인 없이는 안 건드림"으로 90분에 그쳤는데,
    #   그 사이 이 봇의 실제 안전망이 CPU감시가 아니라 다른 걸로 바뀌었다:
    #   서버측 손절(2026-08-07, 봇 다운 중에도 거래소가 직접 자름) + 외부청산 감지(2026-08-25,
    #   재기동하면 거래소 상태와 자동 대조) + 역행경보(2026-08-25). 즉 지금 CPU행감지가
    #   막던 "손절 지연"은 이미 서버측 손절이 대신 막고 있다 — 문턱을 늘려도 실위험 증가 없음.
    #   사용자 확인 후 적용("바꿔", 2026-08-25).
    "margin_short_trader": 21600,
    "margin_short_wide_trader": 21600,   # ★ 2026-08-25: 원본과 동일 구조·동일 폴링이라 같은 값
    "quietpump_long_paper": 21600,       # ★ 2026-08-26: 순수 모의·I/O바운드, 다른 모의봇과 동일
    "prom_long_paper": 21600,            # ★ 2026-08-30: 순수 모의·I/O바운드, 동일
    "coinpan_monitor": 21600,            # ★ 2026-08-27: 15분 주기 웹수집, CPU 거의 안 씀
    "accum_trader": 5400,
    # ★ 2026-08-17: 위 세 봇과는 원인이 다른 오탐 — 이 둘은 폴링주기 자체는 60초로 짧은데,
    # 사이클당 실연산(requests.get 응답대기+간단한 float비교+JSON저장)이 너무 가벼워서 CPU
    # user+system 시간이 30분 동안 0.05초(HANG_CPU_EPSILON)를 못 넘김 — 실측 로그로 확인:
    # bc_rule_shadow_paper는 포지션을 실제로 계속 추적 중인 동안에도(HEMIUSDT 3시간+ 보유)
    # 30~31분 간격으로 계속 "행상태"로 오판돼 강제재시작당함(logs/watchdog.log 08:56~13:11
    # 연속 8회). 두 봇 다 순수모의(매매 API 미호출, 실거래자금 무관)라 문턱을 넉넉히 늘려도
    # 실위험은 없음 — 진짜 몇 시간씩 죽는 경우는 아래 "죽음 감지"(proc.poll) 경로가 별도로 잡음.
    "bc_rule_shadow_paper": 21600,      # I/O바운드라 CPU기반 행감지가 구조적으로 안 맞음, 6h 여유
    "oi_divergence_short_paper": 21600, # 동일 원인(logs/watchdog.log 10:59~13:01 연속 5회 오탐 확인)
}
# ★ 2026-08-17(watchdog 신뢰성 감사, 사용자 지적 "watchdog가 왜 맨날 문제가 되는거야"로 착수):
# 위 두 봇에서 발견한 원인(I/O바운드 경량폴링이라 CPU기반 행감지 문턱을 구조적으로 못 넘음)이
# 사실상 전체 함대에 재현되는 걸 로그포렌식으로 확인 — logs/watchdog.log 최근 33.5시간 창에서
# 아래 목록 전부 봇당 ~64~65회(≈30분 간격) "행상태 감지"가 찍힘. 전부 매매 API 미호출(순수모의·
# 순수로깅·알림전용)이라 문턱을 늘려도 실거래 위험 없음. margin_short_trader·accum_trader도 같은
# 패턴이 확인됐지만 실전(real-money) 봇이라 사용자 확인 없이는 안 건드림(would_change_log.md 참고).
_PURE_PAPER_LOGGING_BOTS = [
    "retest_trader", "em_trader", "igniter_alert", "ml_trader", "rsi_extreme_short_paper",
    "crossex_logger", "volume_radar", "rsi_trader", "futures_logger",
    "upbit_notice_monitor", "binance_notice_monitor", "bithumb_notice_monitor",
    "reaction_paper_trader", "orderflow_logger", "breadth_monitor",
]
for _b in _PURE_PAPER_LOGGING_BOTS:
    HANG_CHECK_OVERRIDE_SEC.setdefault(_b, 21600)
# alt_momentum_long_paper: 자체 CHECK_SEC=21600(hybrid_trader와 동일 6시간 일봉기반) —
# 문턱을 CHECK_SEC와 똑같이 두면 경계오탐(상단 2026-07-26 주석 참고) 나므로 2배로 여유.
HANG_CHECK_OVERRIDE_SEC["alt_momentum_long_paper"] = 43200
# shadow_fleet: POLL_SEC=180이지만 신호 없는 사이클은 티커조회 1회로 끝나 CPU를 거의 안 씀.
# 다른 순수모의 로깅봇들과 동일하게 6시간.
HANG_CHECK_OVERRIDE_SEC["shadow_fleet"] = 21600
# tg_bot: 그 자체는 매매 안 하지만 margin_manual_long_trader의 실질적 안전망(15초 폴링으로
# 트레일링/손절을 직접 처리)이라 6시간까지는 안 늘리고 core_trader/core_leveraged와 같은
# 90분으로 절충 — 오탐 소음은 없애되 진짜 행 상태는 비교적 빨리 잡음.
# ★ 2026-08-25: 실측 결과 90분에서도 계속 오탐 재현(watchdog.log, margin_short_trader와
#   같은 구조적 원인 — 15초 폴링+긴 텔레그램 롱폴링이라 CPU가 거의 안 쌓임). 다만 이 봇은
#   재량 포지션 안전망 역할이 있어 순수 로깅봇(6시간)만큼은 안 늘리고 3시간으로 절충한다.
#   확인: 2026-08-25 시점 재량 포지션(빗썸롱·마진숏·마진롱) 전부 0건 — 지금 당장 위험은 없다.
#   재량 포지션이 열려 있는 동안 진짜 행 상태가 나면 최대 3시간 늦게 잡힐 수 있다는 점은 남는다.
HANG_CHECK_OVERRIDE_SEC["tg_bot"] = 10800
_last_cpu_time: dict[str, float] = {}
_last_active_ts: dict[str, float] = {}

# ★ 2026-08-08: 재시작 텔레그램 알림 과다 문제 — 조용한 로깅/모의매매 봇들이 30~45분 간격
# 무더기 행상태 감지로 재시작될 때마다 전부 알림이 가서 스팸이 됨. 실제 돈이 걸린 봇만
# 알림 보내고 나머지는 로그(watchdog.log)에만 남기도록 축소.
# ★ 2026-08-13: margin_short_trader/accum_trader도 "행상태 감지→강제재시작"이 정상 유휴
# 구간에서도 자주 떠서 텔레그램 스팸으로 느껴진다는 사용자 피드백 → 완전 제거(로그만).
# 실제 위험 알림(🚨 보호장치 감시, 캐스케이드 체결)은 별도 경로라 영향 없음.
ALERT_ON_RESTART = set()
# ★ 2026-08-12: 한 번 체크하고 정상종료(exit=0)하는 설계인 봇들 — while True 루프 없이
# "체크→종료"를 반복하는 구조라 watchdog이 매 사이클(~50초)마다 "죽음 감지→재시작"으로
# 오인해 콘솔/로그가 스팸으로 도배됨(버그 아님, by design). 이 목록에 있으면 exit=0일 때만
# 로그레벨을 낮추고 문구도 완화 — 진짜 비정상 종료(exit!=0)는 여전히 WARNING으로 남음.
# ★ 2026-08-26(점검 발견): _protection_audit도 "체크→종료" 설계다. 이 스크립트는
#   2026-08-07에 만들어졌으나 **어디에서도 호출되지 않아 한 번도 실행된 적이 없었다**
#   (watchdog BOTS·schtasks·프로세스 어디에도 없었고 grep 호출부 0곳).
#   "15분 주기 무보호 감사"가 문서에만 있고 실제로는 존재하지 않았다 — 실거래 마진숏 2건이
#   무보호인데 아무도 몰랐던 직접 원인. 등록해서 실제로 돌게 한다.
ONESHOT_BOTS = {"margin_manual_long_trader", "_protection_audit", "ledger_reconcile",
                "positioning_logger"}

# ★ 2026-08-29: ONESHOT은 종료 즉시 재기동한다(~40초 주기). 거래소 원장을 페이지네이션으로
#   긁는 ledger_reconcile을 그 주기로 돌리면 레이트리밋에 걸린다 — 최소 재기동 간격을 둔다.
#   여기 없는 ONESHOT은 기존대로 즉시 재기동(동작 변경 없음).
ONESHOT_MIN_INTERVAL_SEC = {
    "ledger_reconcile": 1800,     # 30분. 달력이 보는 순손익 원장 갱신용
    "positioning_logger": 3600,   # 1시간. 데이터가 1시간 단위라 그보다 자주 돌 이유가 없다
}
_oneshot_next_at = {}             # name -> 이 시각 이후에만 재기동

BOTS = {
    "tg_bot":                ROOT / "scripts" / "tg_bot.py",
    # ★ 2026-08-26: 실거래 포지션의 서버측 손절이 실제 거래소에 살아있는지 재검증(무보호면 🚨).
    #   ONESHOT이라 매 사이클(~50초) 돌며 체크하고 종료한다.
    "_protection_audit":     ROOT / "scripts" / "_protection_audit.py",
    # ★ 2026-08-29(사용자 발견 "달력 합계가 이상한데"): /달력이 보는 순손익 원장을 갱신한다.
    #   봇 CSV엔 펀딩비·수수료가 없어 달력이 실제보다 32 USDT 낙관적이었다. 읽기전용(GET만).
    #   ONESHOT + 30분 간격(ONESHOT_MIN_INTERVAL_SEC) — 원장 페이지네이션이라 매 사이클은 과하다.
    "ledger_reconcile":      ROOT / "scripts" / "ledger_reconcile.py",
    # ★ 2026-09-03: 포지션 쏠림(개미/큰손 롱숏비·미결제약정) 적재. 매매 무관, GET만.
    #   바이낸스가 이 이력을 30일치만 줘서 백테스트가 불가능하다 — 지금부터 직접 쌓는다.
    #   ONESHOT + 1시간 간격. 놓친 구간은 다음 실행이 자동으로 메운다(최근 30건 조회 후 중복 스킵).
    "positioning_logger":    ROOT / "scripts" / "positioning_logger.py",
    # "claude_intelligence" 제거 (2026-07-09): claude CLI 서브프로세스 호출이 계속 실패
    # (WinError 2, 5분마다 헛돌기만 함) + 사용자 지시로 오토리서치/루프 당분간 중단.
    # "claude_intelligence":   ROOT / "scripts" / "claude_intelligence.py",  # CI Mode
    # "swing_monitor" 제거 (2026-06-30): 스윙 전략 없음, 불필요
    # "vb_trader" 제거 (2026-06-25): forward t=-4.29, 승률17% — 폐기 확정
    # "retest_trader" 제거 (2026-08-20, 기록감사 26봇 전수조사): 60일간 신규거래 0건(강세장
    # 조건 미충족 상태 지속), 그나마 쌓인 78건도 건당+0.06%(t≈0, 무작위와 구분 불가). 이 속도로는
    # 판정 자체가 영원히 안 남.
    # "retest_trader":         ROOT / "scripts" / "retest_trader.py",
    # "em_trader" 폐기 (2026-08-20): 411건 건당-0.53%/t=-2.31 — 무작위 대조군(-0.15%)보다
    # 나쁘고 자기 게이트(t≥3.0)에 정반대로 실패. volaccum과 같은 부류의 통계적 확정손실.
    # "em_trader":              ROOT / "scripts" / "em_trader.py",
    # "igniter_alert" 제거 (2026-08-20): 알림전용 봇인데 notify.py 화이트리스트에 안 걸려
    # 알림이 100% 차단 중이었음(존재이유 상실). 산출 CSV 2종도 읽는 코드 0곳. docstring이
    # 약속한 "ML 학습에 사용"할 코드도 없음 — 3가지 존재이유가 전부 사망 상태.
    # "igniter_alert":          ROOT / "scripts" / "igniter_alert.py",
    # "ml_trader" 폐기 (2026-08-20): 423건 건당+0.02%/t=+0.07 — 60일·423건을 쌓고도
    # 완전한 무(無). em_trader와 같은 igniter_model.pkl을 공유하는 계열, 함께 정리.
    # "ml_trader":              ROOT / "scripts" / "ml_trader.py",
    "core_trader":           ROOT / "scripts" / "core_trader.py",      # 코어 BTC 사이클타이밍 (검증엔진·모의 추적, core_leveraged 벤치마크로 존치 — 판단보류, 2026-08-20)
    "core_leveraged":        ROOT / "scripts" / "core_leveraged.py",   # 코어+2배 레버리지 — ★실거래(armed), 2026-08-20 확인
    # "blowoff_short_paper" 은퇴 (2026-07-12): ①선물(fapi) 가격만 조회해 선물 미상장 코인(PYR 등)을
    # 추적 못 하는 버그 — PYR 모의숏이 실제 -28% 하락(숏 +17%)인데 "가격 무변동, -0.2%"로 오기록됨.
    # ②역할 종료: 검증된 실전봇(margin_short_trader, 현물API 사용·정상)이 대체.
    # "blowoff_short_paper":   ROOT / "scripts" / "blowoff_short_paper.py",
    "margin_short_trader":   ROOT / "scripts" / "margin_short_trader.py",  # ★거래량폭발 급등주 마진숏 실전 (검증완료, 증거금상한100·2배, 2026-07-11)
    # ★ 2026-08-25(버그헌터 발견): 완화판(진입 7h+15~30%)도 실거래 봇인데 여기 없어서 수동기동
    #   상태였다 — 크래시·행·재부팅 시 재시작이 안 돼 만기청산·트레일링·외부청산감지·역행경보가
    #   전부 멈춘다(서버측 STOP_MARKET만 남음). 2026-08-22 core_lev 누락 사고와 같은 구조라 등록.
    "margin_short_wide_trader": ROOT / "scripts" / "margin_short_wide_trader.py",  # ★진입완화판 마진숏 실전 (2026-08-25 신설)
    # ★ 2026-08-26: 조용한급등 롱 모의봇(순수 모의, 매매 API 미호출).
    #   PREREG_SWEEP_BINANCE 봉인을 통과한 첫 후보를 60건까지 검증하는 중이라
    #   중간에 죽으면 표본 수집이 끊긴다(사전등록 마감 2026-10-26).
    "quietpump_long_paper":  ROOT / "scripts" / "quietpump_long_paper.py",  # ★조용한급등 롱 모의 (2026-08-26 신설)
    "prom_long_paper":       ROOT / "scripts" / "prom_long_paper.py",       # ★PROM 롱 모의 (2026-08-30 신설, PREREG_PROM_LONG.md)
    "coinpan_monitor":       ROOT / "scripts" / "coinpan_monitor.py",       # ★코인판 게시판 수집 (2026-08-27 신설, 관찰 전용·매매 무관)
    # "margin_manual_long_trader" 제거 (2026-08-20, 기록감사 재확인): 08-15에 이미 발견된 대로
    # __main__ 블록이 없어 watchdog이 등록해도 프로세스가 실제로 뜬 적이 없음(실측 확인 —
    # 커맨드라인에 이 파일이 걸린 프로세스 0개). 30~60초마다 "재기동"만 반복하는 완전한 placebo.
    # 진짜 트레일링/손절 감시는 tg_bot.py의 15초 폴링 루프가 이 파일을 직접 import해서 수행 중
    # (정상 작동, 08-15 확인) — 그래서 **파일 자체는 삭제하지 않는다.** 여기 등록만 제거.
    # "margin_manual_long_trader": ROOT / "scripts" / "margin_manual_long_trader.py",
    # "rsi_extreme_short_paper" 제거 (2026-08-20): 58건 건당-0.02% — 무작위와 구분 불가.
    # 손절 로직 자체가 없음(시간만기 청산뿐이라는 게 08-19 감사에서 지적돼 이미 disarm 상태).
    # "rsi_extreme_short_paper": ROOT / "scripts" / "rsi_extreme_short_paper.py",
    "oi_divergence_short_paper": ROOT / "scripts" / "oi_divergence_short_paper.py",  # OI다이버전스 숏 (레딧리서치 1순위 후보, 순수모의, 2026-08-15) — 9/2 마감 대상
    "bc_rule_shadow_paper": ROOT / "scripts" / "bc_rule_shadow_paper.py",  # b/c룰(손실축소) 모의 병렬검증 — 실전 진입 미러링, 순수모의, 2026-08-16 — 9/2 마감 대상
    "alt_momentum_long_paper": ROOT / "scripts" / "alt_momentum_long_paper.py",  # 알트 모멘텀 Top3 롱 모의(hybrid_trader 알트선별 로직, BTC강세게이트 없이 상시가동, 100건 목표, 순수모의, 2026-08-17) — 9/2 마감 대상
    "shadow_fleet": ROOT / "scripts" / "shadow_fleet.py",  # 그림자 함대 — 같은 신호에 청산/필터 변형 6개를 병렬 적용해 짝비교(순수모의, 선물전종목+펀딩비·수수료 반영, 2026-08-19) — 9/2 마감 대상
    # "hybrid_trader" 제거 (2026-08-20): 가동 이래 실거래 0건(BEAR 게이트 상시성립 — SMA200
    # 하회 지속). alt_momentum_long_paper가 이 봇의 알트선별 로직에서 BTC게이트만 뺀 상위호환이라
    # 이미 완전 포섭됨(watchdog 주석에 그 관계가 명시돼 있었음).
    # "hybrid_trader":         ROOT / "scripts" / "hybrid_trader.py",
    "crossex_logger":        ROOT / "scripts" / "crossex_logger.py",   # 교차거래소 선행신호 로거 (순수로깅·매매0, 격리) — 재구성 불가 데이터, 존치
    "volume_radar":          ROOT / "scripts" / "volume_radar.py",     # 거래대금 급증 레이더 (순수로깅·매매0, 격리) — margin_short 9/19 판정에 필터후보로 연동, 판단보류
    # "accum_trader" 폐기 (2026-08-20): 185건 건당-0.36%/t=-2.06 — 무작위보다 나쁨, 통계적으로
    # 음수 확정(live_guard 미arm 상태로 전량 모의였음).
    # "accum_trader":          ROOT / "scripts" / "accum_trader.py",
    # "newlisting_monitor" 은퇴 (2026-07-13): 6일간 실전체결 0건(유일 실전창 7/3에도 "90초내 체결가못잡음"으로
    # 놓침, 7/7 23시 전체disarm 후 재arm 안 됨), API타임아웃·DNS실패로 최대 7시간 다운 반복 — 신뢰성 문제.
    # 게다가 근본 전략도 이미 죽음(STRATEGY.md: 신규상장펌핑 5분만 늦어도 11/11 전패) — 재검토(2026-07-13)해도
    # 숏 반전도 안 됨(업비트/빗썸 원화프리미엄 현상이라 바이낸스엔 거의 안 옮음, n=3뿐).
    # "newlisting_monitor":    ROOT / "scripts" / "newlisting_monitor.py",
    # "rsi_trader" 폐기 (2026-08-20): 77건 건당-0.76%/t=-2.12 — volaccum(이미 폐기)과 동급의
    # 통계적 확정손실(live_guard 미arm, 전량 모의였음).
    # "rsi_trader":            ROOT / "scripts" / "rsi_trader.py",
    # "cascade_trader" 은퇴 (2026-07-20): 07-08에 108조합 그리드서치+봉종가 백테스트착시 발견으로
    # "구제 불가" 확정된 뒤에도 모의로 계속 돌았음. 어디서도 이 데이터/로직을 안 씀(import·파일참조 0건),
    # 최근 실측도 -1.5~-2.2% 손절만 반복 확인 — 새 정보 없이 이미 죽은 판정만 재확인하는 상태.
    # newlisting_monitor(07-13)와 동일 사유로 완전 제거.
    # "cascade_trader":        ROOT / "scripts" / "cascade_trader.py",
    "futures_logger":        ROOT / "scripts" / "futures_logger.py",   # 선물 펀딩/OI/롱숏 로거 (순수로깅·매매0, margin_short 오버레이 필터 후보용, 2026-07-13 유니버스 재정렬 후 재개) — 공식 히스토리API로 대체 가능한지 확인 필요(2026-08-20)
    # "lead_ws_trader" 폐기 (2026-07-02): 716건 비용후 -0.252%/t-4.07 통계적 확정손실 (#41)
    # "momentum_trader" 폐기 (2026-07-03): 90일 절제백테 전 구간(15분~168H) 전부 음수(t-17.5~-1.3),
    # 실측 15건도 -46.21%p 일치 확인. "오른 코인 추격"이 알트에서 전 타임프레임 역효과 (#42)
    # "volaccum_trader" 폐기 (2026-08-12): 256건 누적 승률42.6%/평균-0.85% — 4개AI
    # (ChatGPT·Perplexity·제미나이·MiniMax) 만장일치 "통계적 확정손실" 판정. 후속 아이디어
    # 없는 한 재개 안 함.
    # "volaccum_trader":       ROOT / "scripts" / "volaccum_trader.py",  # 거래량매집 단타 (#43, 20~80배 스파이크 모의, TP+3% SL-3% 2H)
    # "spike_tracker" 제거 (2026-06-30): volume_radar와 역할 겹침, 불필요
    "upbit_notice_monitor":  ROOT / "scripts" / "upbit_notice_monitor.py",   # 업비트 상장공지 감지지연 측정 (순수로깅·매매0) — reaction_paper_trader가 소비
    "binance_notice_monitor": ROOT / "scripts" / "binance_notice_monitor.py", # 바이낸스 상장공지 감지지연 측정 (순수로깅·매매0) — reaction_paper_trader가 소비
    # "bithumb_notice_monitor" 제거 (2026-08-20): 산출물(bithumb_notice_events.csv)을 읽는
    # 코드가 프로젝트 어디에도 없음(reaction_paper_trader는 업비트·바이낸스만 읽음) — 수집만
    # 하고 아무도 안 보는 상태였음.
    # "bithumb_notice_monitor": ROOT / "scripts" / "bithumb_notice_monitor.py",
    # "reaction_paper_trader" 제거 (2026-08-20): 최근 13일간 신규거래 0건(상장공지 자체가
    # 희소), 쌓인 8건도 건당-2.23%. 이 속도로는 판정표본(30건)까지 4개월 걸림 — 신호원(상장공지
    # 모니터 2종)은 남기되 이 소비자만 정리.
    # "reaction_paper_trader": ROOT / "scripts" / "reaction_paper_trader.py",
    "orderflow_logger":      ROOT / "scripts" / "orderflow_logger.py",       # 체결방향 불균형(OFI) 로거 (순수로깅·매매0, 백테스트용 데이터 축적) — 재구성 불가 데이터, 존치. 단 whale_print 부산물(소비자 은퇴함)은 후속 정리 검토
    # "quiet_accum_screener" 임시 제거 (2026-07-09): exit=1 크래시루프 발견,
    # 35초마다 재시작되며 텔레그램 재시작 알림 스팸 — 원인 진단 후 복구.
    # "quiet_accum_screener":  ROOT / "scripts" / "quiet_accum_screener.py",   # #47 조용한 매집 스크리너 (거래대금상위+안오름+OFI매수우위 겹침, 순수로깅·매매0)
    "breadth_monitor":       ROOT / "scripts" / "breadth_monitor.py",       # 시장전체 로테이션(breadth) 배경모니터 (순수로깅·매매0) — 2026-08-20 상관리스크 분석에 실사용된 전례로 존치가치 확인
    # "whale_print_paper_trader" 은퇴 (2026-07-21): forward 1,733건 재판정 결과 day-clustered t-4.57,
    # 비용후 평균-0.85% — 통계적 확정손실. 원 가설(BLUR n=1) 반증됨. STRATEGY.md 참조.
    # "whale_print_paper_trader": ROOT / "scripts" / "whale_print_paper_trader.py",
}

# ★ 2026-08-20 기록감사(26봇 전수조사, 근거는 docs/would_change_log.md 참조) — 위에서
# 11개 제거. 무작위 대조군(random_trades.csv, 46건 건당-0.15%)보다 표본이 충분한데도
# 나쁘거나(em/ml/accum/rsi_trader/rsi_extreme_short_paper), 표본이 몇 달째 안 쌓이거나
# (retest_trader/hybrid_trader/reaction_paper_trader), 존재이유가 이미 죽은(igniter_alert/
# bithumb_notice_monitor) 봇들. margin_manual_long_trader는 성적과 무관하게 08-15부터
# 알려진 placebo 등록이라 제거(파일은 tg_bot이 계속 씀, 삭제 안 함).


def send_tg(text: str) -> None:
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        tg = cfg.get("telegram", {})
        token = tg.get("bot_token", "")
        chat_id = str(tg.get("chat_id", ""))
        if token and chat_id:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
    except Exception as e:
        log.warning(f"[send_tg] 실패: {e}")


EXTRA_ARGS: dict[str, list[str]] = {
    "claude_screener_dry":   ["--dry-run"],
    "claude_screener_watch": ["--watch-mode"],
    "swing_monitor":         ["--loop"],
    # vb_trader 제거됨
    "retest_trader":         ["--dry-run"],   # 합격선(모의30건+, 평균>0) 통과 전 실거래 금지
    "em_trader":             ["--dry-run"],   # #24 게이트(CLEAN n≥50, 비용0.30%후 t≥3, 강건성) 통과 전 실거래 금지
    "ml_trader":             ["--dry-run"],   # #31 게이트(CLEAN n≥30, 비용0.30%후 t≥2.5, 베이스라인 초과) 통과 전 실거래 금지
    "core_trader":           ["--dry-run"],   # 코어 BTC타이밍 모의 — 실거래는 사용자 승인
    "hybrid_trader":         ["--dry-run"],   # 하이브리드 모의 — 강세 forward 데이터 수집 전 실거래 금지
    "claude_intelligence":   [],              # 2026-06-10 dry-run 전환 — 검증 전 실거래 금지 원칙
}

# 인스턴스 식별용 kill 키워드 매핑
KILL_KEYWORDS: dict[str, str] = {
    "claude_screener_dry":   "--dry-run",
    "claude_screener_watch": "--watch-mode",
    # vb_trader: 키워드 제거 (2026-06-10) — "--dry-run" 키워드 잔존으로 --live 인스턴스를
    # 못 죽여 싱글톤 포트 충돌 → 재시작 크래시 루프 발생했던 버그 수정
}


def kill_existing(name: str) -> None:
    extra_kw = KILL_KEYWORDS.get(name)
    script_kw = "claude_screener.py" if "screener" in name else f"{name}.py"
    for p in psutil.process_iter(["pid", "cmdline", "name"]):
        try:
            if "python" not in (p.info["name"] or "").lower():
                continue  # 셸 래퍼 오인 종료 방지
            parts = p.info["cmdline"] or []
            # 스크립트 파일명이 독립 인자로 있을 때만 매칭 (문자열 내부 포함 방지)
            match = any(part.endswith(script_kw) for part in parts)
            if extra_kw:
                match = match and extra_kw in parts
            if match and p.pid != os.getpid():
                log.warning(f"[{name}] 기존 PID {p.pid} 종료")
                p.terminate()
                try:
                    p.wait(timeout=5)
                except psutil.TimeoutExpired:
                    p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def start_bot(name: str, script: Path) -> subprocess.Popen:
    kill_existing(name)
    time.sleep(3)  # 기존 프로세스 완전 종료 + lockfile 정리 대기
    # lockfile 강제 삭제 (atexit 미실행으로 남은 경우)
    if name == "alt_monitor":
        for lf in [ROOT / "data" / "alt_monitor.pid", ROOT / "data" / "bot.lock"]:
            try:
                lf.unlink(missing_ok=True)
            except Exception as e:
                log.warning(f"[{name}] lockfile 정리 실패({lf}): {e}")
    log.info(f"[{name}] 시작")
    extra = EXTRA_ARGS.get(name, [])
    # CREATE_NO_WINDOW: 콘솔창 안 띄움(봇은 파일로 로깅 → stdout 불필요). 창 클러터 방지.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, str(script)] + extra,
        cwd=str(ROOT),
        creationflags=flags,
    )
    time.sleep(5)  # 새 프로세스가 lockfile 쓸 시간 확보
    return proc


def _tree_cpu_seconds(pid: int) -> float | None:
    """프로세스 트리(부모+모든 자손) CPU 누적초 합. 조회 불가 시 None.
    ★ 2026-09-01(버그헌터 감사 2위 수정): 봇은 런처 패턴이라 proc.pid(부모 스텁)는
    자식을 기다리기만 해서 CPU가 거의 안 는다 — 부모만 재면 **일 잘 하는 봇이 매번
    행상태로 오판**돼 강제재시작됐다(누적 1만회+, 청산지연 실사례 2건). 자식까지 합산."""
    try:
        p = psutil.Process(pid)
        total = 0.0
        for pr in [p] + p.children(recursive=True):
            try:
                c = pr.cpu_times()
                total += c.user + c.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _reset_hang_tracking(name: str, proc: subprocess.Popen, now: float) -> None:
    """새로 시작/재시작한 프로세스의 행상태 추적을 초기화. start_bot() 직후 항상 호출."""
    cpu = _tree_cpu_seconds(proc.pid)
    _last_cpu_time[name] = cpu if cpu is not None else 0.0
    _last_active_ts[name] = now


HANG_CPU_EPSILON = 0.05   # ★ 2026-07-26 배포 당일 발견: cur > prev(증가폭 무관, 1틱이라도 늘면 진행중
# 으로 판정)로는 실전에서 안 잡힘 — 45분+ CPU delta=0(수동 90초 창으로 재확인)인데도 watchdog 자체는
# 살아서 30초마다 정상 체크 중이었는데 "행상태 감지"가 끝내 안 뜸. 원인 추정: 진짜 행 상태에서도
# Windows가 커널레벨 미세 틱(APC 전달·페이지폴트 등)을 프로세스에 붙여 cur이 아주 미세하게(수 ms)
# 늘어날 수 있어, cur > prev만으로는 매 체크마다 우연히 조건이 참이 돼 last_active가 계속 리셋되고
# 절대 문턱에 못 닿을 수 있음. "의미있는 진행"만 진행으로 인정하도록 최소 증가폭 기준 추가.
# ★ bug-hunter 검토: 처음엔 0.5초로 잡았으나, hybrid_trader(문턱43200s=자기 CHECK_SEC21600×2 —
# 문턱 안에 사이클이 딱 2번뿐)와 core_trader/core_leveraged(문턱5400s=CHECK_SEC1800×3 — 사이클
# 2~3번뿐)는 사이클당 실제 연산(단일 BTC 캔들 조회+지표계산 정도)이 가벼워 0.5초를 못 채우면
# 건강한 봇이 오탐-강제킬될 위험 지적받음. Windows 타이머 틱(통상 15.6ms)보다는 충분히 크면서
# 가벼운 사이클도 오탐 안 하도록 0.05초(50ms)로 하향 — 실측검증 전까지는 가설적 수정임을 유의.

def _check_hang(name: str, proc: subprocess.Popen, now: float) -> bool:
    """CPU 누적시간이 HANG_CHECK_SEC 동안 HANG_CPU_EPSILON(현재 0.05초)+ 안 늘면 True(행상태로 판단).
    proc.poll()로는 못 잡는, 살아있지만 멈춘 프로세스 감지용(2026-07-26 신설, 상세는 상단 주석)."""
    cur = _tree_cpu_seconds(proc.pid)   # ★ 2026-09-01: 부모+자식 트리 합산(상세는 _tree_cpu_seconds)
    if cur is None:
        return False  # 조회 자체가 안 되면 판단 보류(죽었으면 다음 사이클에 poll()이 잡음)
    prev = _last_cpu_time.get(name)
    # cur < prev = 자식이 죽고 새로 떠서 트리 CPU 합이 줄어든 경우 — 그것 자체가 활동이므로
    # 진행으로 인정하고 기준선을 재설정한다(안 하면 행 타이머가 계속 흘러 오판 강제킬).
    if prev is None or cur - prev >= HANG_CPU_EPSILON or cur < prev:
        _last_cpu_time[name] = cur
        _last_active_ts[name] = now
        return False
    last_active = _last_active_ts.get(name, now)
    threshold = HANG_CHECK_OVERRIDE_SEC.get(name, HANG_CHECK_SEC)
    return (now - last_active) > threshold


def write_weekly() -> None:
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "weekly_summary.py")],
            cwd=str(ROOT), timeout=30,
        )
    except Exception as e:
        log.warning(f"[weekly_summary] 실패: {e}")


def write_session(target_date: str | None = None) -> None:
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "session_writer.py")]
            + ([target_date] if target_date else []),
            cwd=str(ROOT), timeout=30,
        )
    except Exception as e:
        log.warning(f"[session_writer] 실패: {e}")


def run_ai_analyze() -> None:
    out = ROOT / "docs" / f"ai_analysis_{date.today().isoformat()}.md"
    if out.exists():
        log.info("[ai_analyze] 오늘 분석 이미 존재, 스킵")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ai_analyze.py")],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", timeout=120,
        )
        if result.returncode == 0 and out.exists():
            summary = result.stdout[-600:].strip()
            send_tg(f"📊 AI 분석 완료\n\n{summary}")
            log.info("[ai_analyze] 완료")
        else:
            send_tg(f"❌ AI 분석 실패\n{result.stderr[-300:]}")
            log.warning(f"[ai_analyze] 실패: {result.stderr[-200:]}")
    except subprocess.TimeoutExpired:
        send_tg("❌ AI 분석 타임아웃 (120s)")
        log.warning("[ai_analyze] 타임아웃")
    except Exception as e:
        log.warning(f"[ai_analyze] 예외: {e}")


def run_daily_report() -> None:
    """매일 전략점검 — cascade 실거래 게이트 + 선물신호 축적 + 코어/RT 한 장."""
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "daily_strategy_report.py")],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", timeout=60,
        )
        if result.returncode == 0:
            log.info("[daily_report] 완료")
        else:
            log.warning(f"[daily_report] 실패: {result.stderr[-200:]}")
    except Exception as e:
        log.warning(f"[daily_report] 예외: {e}")


LOCKFILE = ROOT / "data" / "watchdog.pid"


_wd_sock = None  # GC 방지


def _acquire_singleton() -> None:
    """포트 바인딩 싱글톤 — 이미 watchdog가 포트를 점유 중이면 새 인스턴스가
    스스로 종료한다(기존을 살림). 과거 '포트 못 잡으면 기존을 죽이고 차지' 방식은
    동시 기동 시 상호 킬 레이스로 watchdog가 여러 개 공존하는 버그가 있었음
    (2026-06-14: PC 재부팅 누적으로 watchdog 5개 → 각자 봇을 띄워 봇 중복 사건).
    PC 재부팅 시엔 OS가 포트를 회수하므로 새 watchdog가 정상적으로 점유한다."""
    import socket
    global _wd_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind(("127.0.0.1", 47230))  # watchdog 전용 포트
        s.listen(1)                   # listen까지 해서 확실히 점유 (LISTEN 상태로 가시화)
        _wd_sock = s
        atexit.register(s.close)
    except OSError:
        s.close()
        # ★ 2026-08-17(watchdog 신뢰성 감사): 본 프로세스 PID를 같이 남겨야 "왜 watchdog가
        # 2개 떠있었지" 같은 사후조사가 로그만으로 가능함(이번에 PID까지 직접 추적하느라
        # 워크플로우 하나를 통째로 써야 했음).
        log.warning(f"포트 47230 이미 사용 중(본 프로세스 PID={os.getpid()}) — watchdog 이미 실행 중이므로 새 인스턴스 종료")
        sys.exit(0)


def main() -> None:
    _acquire_singleton()
    LOCKFILE.write_text(str(os.getpid()))
    atexit.register(lambda: LOCKFILE.unlink(missing_ok=True))

    log.info("=== 워치독 시작 ===")
    send_tg("🐕 워치독 시작 — 봇 자동 재시작 감시 중")

    # 시작 시 오늘 세션 로그 + 주간 요약 생성
    write_session()
    write_weekly()
    last_date = datetime.now(KST).date()

    last_analysis_date: date | None = None

    procs: dict[str, subprocess.Popen] = {}
    for name, script in BOTS.items():
        procs[name] = start_bot(name, script)
        _reset_hang_tracking(name, procs[name], time.time())
        time.sleep(2)

    while True:
        time.sleep(CHECK_INTERVAL)

        # 날짜 바뀌면 전날 마무리 + 오늘 파일 생성
        today = datetime.now(KST).date()
        if today != last_date:
            write_session(last_date.isoformat())  # 전날 최종 기록
            write_session()                        # 오늘 새 파일
            write_weekly()                         # 7일 롤링 요약 갱신
            last_date = today
            log.info(f"[session] 날짜 변경 → {today} 세션 생성")

        # 매일 00:00 KST AI 분석 + 전략점검(cascade 게이트/선물) 자동 실행
        now_kst = datetime.now(KST)
        if (last_analysis_date != today
                and now_kst.hour == 0 and now_kst.minute < 1):
            run_ai_analyze()
            run_daily_report()
            last_analysis_date = today

        now = time.time()
        for name, script in BOTS.items():
            proc = procs[name]
            if proc.poll() is not None:  # 프로세스 종료됨
                # ★ 2026-08-29: 주기 제한이 걸린 ONESHOT은 간격이 찰 때까지 재기동하지 않는다.
                _iv = ONESHOT_MIN_INTERVAL_SEC.get(name)
                if _iv and name in ONESHOT_BOTS and proc.returncode == 0:
                    if name not in _oneshot_next_at:
                        _oneshot_next_at[name] = now + _iv
                    if now < _oneshot_next_at[name]:
                        continue      # 아직 이르다 — 죽은 채로 둔다(정상)
                    _oneshot_next_at[name] = now + _iv
                    log.info(f"[{name}] 주기점검 완료 → 재기동({_iv//60}분 간격)")
                elif name in ONESHOT_BOTS and proc.returncode == 0:
                    log.info(f"[{name}] 주기점검 완료 → 재기동")
                else:
                    log.warning(f"[{name}] 죽음 감지 (exit={proc.returncode}) → 재시작")
                if name in ALERT_ON_RESTART:
                    send_tg(f"⚠️ <b>{name}</b> 종료됨 → 자동 재시작")
                write_session()  # 재시작 시점 기록 업데이트
                proc.wait()  # 이미 죽은 프로세스지만 핸들 명시적 반납(누수 방지, 행상태분기와 통일)
                time.sleep(2)
                procs[name] = start_bot(name, script)
                _reset_hang_tracking(name, procs[name], time.time())
            elif _check_hang(name, proc, now):
                _th = HANG_CHECK_OVERRIDE_SEC.get(name, HANG_CHECK_SEC)
                log.warning(f"[{name}] 행상태 감지(CPU {_th//60}분+ 무변화) → 강제 재시작")
                if name in ALERT_ON_RESTART:
                    send_tg(f"🥶 <b>{name}</b> 행상태(멈춤) 감지 → 강제 재시작")
                write_session()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                time.sleep(2)
                procs[name] = start_bot(name, script)
                _reset_hang_tracking(name, procs[name], time.time())


if __name__ == "__main__":
    main()
