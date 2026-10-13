# 2026-10-13 크립토 일일 브리핑

## 한줄 요약
숏 전략·BTC 200일선 전제를 깨뜨릴 새로운 구조적 사건은 확인되지 않았다 — 한국 증시(반도체주) 급락 여파로 BTC가 장중 $81,000대까지 밀렸다가 $83,000대로 회복했고, 내일(10/14) 미국 CPI 발표가 유일한 단기 변수다.

## 숏전략 영향
- **리스크 신호 없음.** 알트코인을 구조적으로 밀어올릴 호재(확정 알트시즌, 지속 상승 촉매, 규제 호재)는 검색으로 확인되지 않음.
- 알트시즌 지수: 검색상 가장 최근 확인 가능한 수치는 9/19 기준 48(KuCoin) — 저장소 10-06 기록의 "61"보다 낮은 값이고, 10월 갱신치는 검색으로 확인 불가. 완전 알트시즌 문턱 75에는 여전히 미달. 사용자 측 자체 데이터(`breadth_events.csv`)로도 "동반 급등" 흔적이 없었다는 기존 결론과 상충되지 않음.
- 바이낸스 상장폐지: **이번 주 신규 스팟 공지는 확인되지 않음**(Binance Alpha 피처드 목록 제외 10건은 스팟 거래와 무관). 기존 확정분(ACX·HFT·PIVX·PYR·VANRY·VIC) 출금 마감이 10/17 03:00 UTC로 임박(약 4일 남음) — `delist_guard.py`는 여전히 그림자 모드(10-04 #43 판정 유지, 변경 없음).
- 10/13 한국 증시(반도체 밸류에이션 우려로 전주 코스피 급락 재점화 추정) 급락과 함께 비트코인이 장중 $81,000 아래로 떨어졌다가 Asia 세션 중 회복, 미 장 기준 $83,000대 안정 — 이 패턴(한국발 리스크오프 → BTC 단기 급락 → 수시간 내 회복)은 7~8월에도 관찰된 바 있어 알트 숏 가정을 깨뜨리는 "지속 상승" 신호는 아님. 다만 리스크오프 국면에서는 알트가 더 크게 흔들릴 수 있어 참고.
- 24시간 청산 약 $771M(롱 $685.6M 비중) — 급락분 되돌림 과정에서 발생한 것으로 보이며, 숏 전략의 핵심 가정(급등 후 되돌림)과 반대 방향(급락 후 반등)이라 직접 연관은 낮음.

## BTC 추세(200일선) 관련
- **200일선 이탈 위험 신호 없음.** BTC는 10/13 기준 $83,000~83,500대(CoinDesk $83,381, Mitrade $83,515)에서 거래 중 — 저장소 trend3 기록(BTC $81,813 vs 200일선 $72,049, 일봉 종가 기준)과 정합적이며 여전히 약 13~16% 위.
- 장중 한때 $81,000 이하로 밀렸으나 ±1% 밴드(약 $71,300~$72,700)와는 거리가 멀어 이탈 위험 아님.
- **내일(10/14, 수) 미국 CPI 발표가 이번 주 유일한 단기 변수.** Bitfinex 분석은 발표 전 BTC가 $81,300~$84,500 범위에서 움직일 것으로 예상. 과거 패턴(8월 CPI 3.4% 예상치 부합 → BTC 소폭 반등)을 참고하되, 결과는 예상 대비 서프라이즈 여부에 좌우되므로 결과 확인 전까지 판단 보류.
- 미 BTC 현물 ETF 자금 흐름은 10/12 기준으로도 유출 기조 지속(10/12 하루 -$65.4M, 별도 집계 -$451.7M 보도도 있어 수치 혼재) — 추세 전환 신호로 보기는 이름. Strategy(옛 마이크로스트래티지)는 BTC 250개 추가 매입으로 매도 압력 상쇄 요인 유지.
- FOMC 10/27~28 회의의 금리인하 확률은 예측시장 기준 약 20~22%로 낮게 형성(동결이 베이스케이스) — 10일 전보다 "인상 가능성 70%대" 같은 공격적 톤은 검색상 재확인되지 않음, 동결 우세로 완화된 분위기.
- 러시아 Sberbank가 12월 암호화폐 거래 서비스 출시 승인을 받았다는 보도 — 국내 전략과 직접 연관은 낮으나 기관 채택 흐름 참고용.

## 참고 뉴스
- [Bitcoin Price Forecast: BTC rebounds despite cautious sentiment](https://www.mitrade.com/au/insights/news/live-news/article-3-2158573-20261013) — 10/13 한국발 리스크오프로 BTC가 $81K대까지 밀렸다가 $83K대 회복, CPI 발표(10/14) 전 $81,300~$84,500 박스권 예상(Bitfinex).
- [Bitcoin Price Today: BTC Rebounds Above $83K](https://blockchainreporter.net/bitcoin-price-today-btc-rebounds-above-83k-kospi) — 코스피 약세 속 BTC 반등, 24시간 청산 약 $771M(롱 $685.6M).
- [Binance Delisting Alert: 20 Crypto Pairs to Go Dark This Week](https://u.today/binance-delisting-alert-20-crypto-pairs-to-go-dark-this-week-whats-next) — Binance Alpha(피처드 목록) 제거 건, 스팟 거래 상장폐지 아님(기존 ACX·HFT·PIVX·PYR·VANRY·VIC 출금마감 10/17과 별개).
- [Bitcoin Recovers After CPI Report Shows 3.4% US Inflation](https://www.kucoin.com/news/flash/bitcoin-recovers-after-cpi-report-shows-3-4-us-inflation) — (배경) 직전 8월 CPI 발표 시 BTC 반응 패턴, 10/14 발표 해석의 참고 기준선.
- [South Korean Stock Selloff Sparks Crypto Trading Surge as Upbit Volume Soars](https://www.cryptometer.io/news/south-korean-stock-selloff-sparks-crypto-trading-surge-as-upbit-volume-soars/) — (배경, 7월 사례) 한국 증시 급락 시 업비트 거래량 급증 패턴 — 이번 주 재현 여부는 확인 안 됨, 구조적 자금이동 단정 근거 아님.

(알트시즌 지수·바이낸스 신규 상장폐지 공지의 10월 13일자 실시간 수치는 검색으로 확인 불가 — 가장 최근 확인 가능한 값만 위에 반영. CME FedWatch 등 실시간 소스로 교차검증 권장.)
