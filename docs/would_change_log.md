# 변경 충동 기록 (30-trade freeze, MiniMax 권고 2026-08-10 도입)

30건 동안 margin_short_trader.py의 어떤 파라미터/로직도 변경하지 않는다.
바꾸고 싶은 생각이 들면 실행하지 말고 여기에만 적는다. 30건 끝나면 이 로그를
한 번에 검토해서 필요한 것만 묶어 적용하고, 다시 새 freeze를 시작한다.

freeze 시작 시점: 2026-08-10, 21건 누적 시점
freeze 종료 목표: 51건 누적 시점 (21+30)
freeze 시작 시 고정된 설정: PUMP_PCT=30, PUMP_PCT_MAX=40, STOP_PCT=40,
  TRAIL_TRIGGER_PCT=15, TRAIL_GIVEBACK_PCT=10, POLL_SEC=60,
  MIN_QUOTE_VOL=3,000,000, NEWLISTING_MAX_AGE_DAYS=30, STRIKE_BLACKLIST_H=7일

## 기록

- 2026-08-10: MiniMax 지적 — 진입임계값(30%)과 손절폭(40%) 갭이 10%p뿐이라 변동성
  큰 알트에서 너무 쉽게 뚫림. 손절폭을 진입폭의 1.5~2배(45~60%)로 재설계할 후보.
  **freeze 종료 후 최우선 검토 대상.**
