"""지금 실거래 봇들이 뭘 들고 있는지 한눈에 보여준다. 종목 추천이 아니라 현재 상태 조회용.
사용법: .venv/Scripts/python.exe scripts/show_positions.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bithumb.binance_guard import _signed

r = _signed('GET', '/fapi/v2/positionRisk').json()
open_pos = [p for p in r if float(p.get('positionAmt', 0)) != 0]

if not open_pos:
    print("지금 열려 있는 선물 포지션 없음")
else:
    print(f"=== 지금 열려 있는 선물 포지션 {len(open_pos)}개 ===")
    for p in open_pos:
        amt = float(p['positionAmt'])
        side = "숏" if amt < 0 else "롱"
        entry = float(p['entryPrice']); mark = float(p['markPrice']); upnl = float(p['unRealizedProfit'])
        pct = (mark/entry - 1) * 100 * (-1 if amt < 0 else 1)
        print(f"  {p['symbol']:14s} {side}  진입 {entry:.6g} → 현재 {mark:.6g} ({pct:+.1f}%)  평가손익 {upnl:+.2f} USDT")
