import requests, re, json, sys
base="https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
prefix="data/futures/um/monthly/klines/"
syms=[]; marker=""
while True:
    r=requests.get(base, params={"delimiter":"/","prefix":prefix,"max-keys":1000,"marker":marker}, timeout=60)
    t=r.text
    ps=re.findall(r"<Prefix>"+re.escape(prefix)+r"([^<]+)/</Prefix>", t)
    syms.extend(ps)
    if "<IsTruncated>true</IsTruncated>" in t:
        m=re.search(r"<NextMarker>([^<]+)</NextMarker>", t)
        marker=m.group(1)
    else: break
usdt=[s for s in syms if s.endswith("USDT")]
print("total prefixes",len(syms),"USDT",len(usdt))
json.dump(usdt, open("all_um_usdt_syms.json","w"))
