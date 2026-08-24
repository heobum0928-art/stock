import requests, json
r=requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo",timeout=30).json()
trading=sorted(s["symbol"] for s in r["symbols"] if s["symbol"].endswith("USDT") and s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL")
json.dump(trading,open("trading_syms.json","w"))
print("TRADING USDT perp:",len(trading))
# leverage brackets for mmr (public? try)
try:
    lb=requests.get("https://fapi.binance.com/fapi/v1/leverageBracket",timeout=20)
    print("leverageBracket status",lb.status_code, lb.text[:200])
except Exception as e: print("lb fail",e)
