# 2026-10-21 크립토 일일 브리핑

## 한줄 요약
구조적으로 전략 가정을 깨뜨리는 새 사건은 없음 — BTC는 200일선 위에서 완충폭을 유지 중이고, 알트 동반급등(알트시즌) 신호도 재점화 조짐이 없다. 다만 10/28 FOMC와 ETF 자금흐름 둔화는 계속 지켜볼 변수.

## 숏전략 영향
- **리스크 신호: 없음 (약함).** "급등한 알트는 되돌림 온다"는 가정을 구조적으로 깨뜨릴 만한 뉴스(알트시즌 본격화, 특정 알트의 지속적 상승 촉매 등)는 오늘 검색에서 확인되지 않았다. 알트시즌 지수는 최근 수 주 정체 상태였고(저장소 기록상 10/05~10/12 61 부근 정체), 오늘 새로 알트 전반이 동반 폭등했다는 뉴스도 없었다.
- **참고 — 거래소 상장폐지**: 바이낸스는 EPIC(Epic Chain)·QUICK(QuickSwap) 현물 거래를 2026-10-28 03:00 UTC에 종료 예정이라고 공지했다(마진 대출은 10/15부터 중단). 10/3 추가된 "상장폐지 공지 30일 이내 코인 숏 차단" 규칙 대상이 될 수 있으니, 두 종목이 신호에 걸리면 이미 차단되고 있는지 확인할 것. 이 외 신규 모니터링 태그/상장폐지 공지는 확인되지 않았다.
- **참고 — 운영 상태**: `would_change_log.md`에 따르면 오늘(10/21) 사용자 결정으로 선물·마진 양쪽 **신규 숏 진입이 전부 중지**된 상태(`max_total_short_notional_usdt`, `engine_caps_usdt`를 1로 낮춤)다. 아래 리스크 판단은 숏이 재개될 경우를 대비한 참고용이며, 현재는 신규 진입 자체가 없다.

## BTC 추세(200일선) 관련
- **이탈 위험 신호: 없음.** BTC는 10/21 기준 약 $82,700~$83,400대에서 거래 중이며(출처: fxstreet, cryptoticker), 저장소 기록상 200일선은 10/14 기준 약 $72,133 — 현재가가 200일선 대비 약 +15% 완충폭을 유지하고 있어 단기 이탈 위험은 낮다.
- **ETF 자금흐름**: 10/19 비트코인 현물 ETF +$527M 순유입(블랙록 IBIT 주도, 한 달 만에 최대치) → 10/20 +$23M으로 급격히 둔화. 10월 전체로는 여전히 순유출(-$65M~-$88M 추정, 소스 간 약간 차이). 이더리움 ETF는 10월 -$10.8억 순유출로 더 약함. 추세를 뒤집을 정도는 아니나 FOMC 전 관망세로 해석됨.
- **FOMC**: 10/27~28 FOMC, 결정 발표는 10/28 (현지시각 오후 2시 ET). 이번 회의는 SEP(점도표) 없는 회의. 예측시장 상 금리 인하 확률은 낮게(약 4~22%, 소스별 편차 큼) 반영 — 급격한 정책 서프라이즈로 BTC가 크게 흔들릴 가능성에 대한 뚜렷한 사전 경고는 없으나, 발표 당일(10/28) 변동성 확대는 예상 범위.
- **중간선거(11/3) 관련**: 시장구조법(CLARITY Act)은 중간선거 전 통과가 "불확실"하다는 분석(TD Cowen 등)이 있으나, 이는 이미 수개월째 알려진 지연 리스크이고 오늘 새로 발생한 사건은 아니다. 즉각적인 200일선 이탈 촉발 요인으로 보지 않음.

## 참고 뉴스
- [ETF inflows of $526.7 million meet a Bitcoin price of $82,708: the levels that decide before the Fed meeting](https://cryptoticker.io/en/bitcoin-price-etf-inflows-fed-meeting-21-october-2026/) — 10/19 ETF 순유입 $527M, BTC $82,708 부근, FOMC(10/28) 전 핵심 레벨 공방.
- [Could renewed ETF inflows push Bitcoin back toward $85,000?](https://www.fxstreet.com/cryptocurrencies/news/bitcoin-price-forecast-btc-eyes-a-break-above-85-000-as-institutional-demand-returns-202610211218) — ETF 수급 재개 시 $85K 재돌파 가능성 분석(10/21).
- [US Spot Bitcoin ETFs Post Second Straight Day of Net Inflows, Led by BlackRock's IBIT](https://finance.biggo.com/news/cadb2bc2-6a62-429f-9dee-061d03508ae4) — IBIT 주도 2일 연속 순유입이나 10/20에는 $23M로 급감.
- [FOMC Meeting Schedule — October 2026](https://fedratecalc.com/fomc-meeting-schedule/october-2026/) — 10/27~28 FOMC 일정, SEP 없는 회의, 발표 10/28 오후 2시 ET.
- Binance 공지: EPIC·QUICK 현물 거래 2026-10-28 03:00 UTC 종료(마진 대출 10/15부터 중단) — [관련 보도](https://fxnewsgroup.com/forex-news/cryptocurrency/binance-to-delist-epic-and-quick/).
