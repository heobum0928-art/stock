import requests,json,time,sys
out=[]
for p in range(1,12):
    r=requests.get('https://www.binance.com/bapi/composite/v1/public/cms/article/list/query',params=dict(type=1,catalogId=161,pageNo=p,pageSize=50),timeout=30).json()
    cs=r['data']['catalogs']
    a=cs[0]['articles'] if cs else []
    if not a: break
    out+=a; time.sleep(0.3)
json.dump(out,open(sys.argv[1],'w'))
print(len(out))
