# Bithumb Night Trader

빗썸 기준으로 `밤 10시~12시` 사이에 메이저 코인만 짧게 보기 위한 로컬/클라우드 대시보드입니다.

현재 방향:

- 목표: `월 3%` 수준의 보수 운용
- 원칙: 자주 안 사고 `BUY`가 뜬 날만 짧게 본다
- 대상: `BTC`, `SOL`, `XRP`, `ETH`

현재 기능:

- 오늘 매매 가능 여부 표시
- 오늘 1순위 종목 1개 추천
- `BUY`, `WATCH`, `SKIP` 진입 판단
- 보유 포지션의 `SELL`, `TRIM`, `HOLD` 매도 판단
- 뉴스 3개 요약 표시
- 30초 자동 새로고침
- 외부 공개용 비밀번호 로그인
- Render 헬스체크 전용 `/healthz` 포함

## 로컬 실행

비밀번호 없이 로컬에서만 볼 때:

```bash
python app.py
```

브라우저에서 `http://127.0.0.1:8080` 접속

비밀번호까지 걸고 싶으면 환경변수를 먼저 넣습니다.

```powershell
$env:DASHBOARD_PASSWORD="원하는비밀번호"
python app.py
```

## Render 배포

1. 이 폴더를 GitHub 저장소에 올립니다.
2. Render에서 `New +` -> `Blueprint` 선택
3. GitHub 저장소 연결
4. `Environment`에서 `DASHBOARD_PASSWORD` 추가
5. `render.yaml` 인식 후 배포
6. 배포 완료되면 Render URL로 접속

## 월 3% 목표용 기준

- 손절: `-1.2%`
- 목표 익절: `+1.8%`
- 트레일링 청산: 최고 수익 이후 `-0.7%`
- 무리한 추격 금지: 추천 종목의 `허용 상단` 넘으면 보수적으로 접근
- `SKIP` 뜨면 쉬기

## 파일

- `app.py`: 실행 진입점
- `server.py`: HTTP 서버와 HTML 대시보드
- `bithumb_client.py`: 빗썸 공개 API 연동
- `news_client.py`: 뉴스 RSS 수집
- `strategy.py`: 종목 추천 및 매도 판단 로직
- `render.yaml`: Render 배포 설정
