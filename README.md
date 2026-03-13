# Bithumb Night Trader

빗썸 기준으로 `밤 10시~12시` 사이에 메이저 코인만 짧게 보기 위한 로컬/클라우드 대시보드입니다.

핵심 화면:

- `시장 상태`: 오늘 매매 가능한 날인지
- `지금 행동`: 지금 사도 되는지, 기다릴지, 쉬어야 하는지
- `종목 선택`: 오늘 가장 먼저 볼 종목
- `종목 비교`: 모바일 카드형으로 매수 상단, 손절가, 익절가 비교
- `매도 시점 확인`: 이미 샀다면 지금 팔지 계산

현재 기준:

- 목표: `월 3%` 수준의 보수 운용
- 대상: 메이저 + 유동성 알트
- 추천 후보 예시: `BTC`, `ETH`, `XRP`, `SOL`, `ADA`, `DOGE`, `LINK`, `AVAX`, `TRX`, `HBAR`, `DOT`, `SUI`
- 손절: `-1.2%`
- 목표 익절: `+1.8%`
- 트레일링 청산: 최고 수익 이후 `-0.7%`

## 로컬 실행

```bash
python app.py
```

브라우저에서 `http://127.0.0.1:8080` 접속

비밀번호까지 걸고 싶으면:

```powershell
$env:DASHBOARD_PASSWORD="원하는비밀번호"
python app.py
```

## Render 배포

1. GitHub 저장소 연결
2. Render에서 `Blueprint` 배포
3. 환경변수 `DASHBOARD_PASSWORD` 추가
4. 배포 완료 후 URL 접속

## 업데이트 반영

```bash
git add .
git commit -m "Update mobile dashboard"
git push
```

## 파일

- `app.py`: 실행 진입점
- `server.py`: HTTP 서버와 HTML 대시보드
- `bithumb_client.py`: 빗썸 공개 API 연동
- `news_client.py`: 뉴스 RSS 수집
- `strategy.py`: 종목 추천 및 매도 판단 로직
- `render.yaml`: Render 배포 설정
