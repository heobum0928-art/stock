"""GDELT DOC API timelinetone — 분기 단위 수집, 5초 제한 준수, 캐시. 사용: python gdelt_tone_fetch.py"""
import requests,json,time,os,datetime as dt
S='C:/Users/heo09/AppData/Local/Temp/claude/C--coinbase/47e47122-86c7-4bda-ad20-d77594f63541/scratchpad/gdelt/'
os.makedirs(S,exist_ok=True)
U='https://api.gdeltproject.org/api/v2/doc/doc'
def chunk(a,b):
    p=S+f'tone_{a:%Y%m%d}_{b:%Y%m%d}.json'
    if os.path.exists(p): return json.load(open(p))
    for tries in range(6):
        time.sleep(7)
        r=requests.get(U,params=dict(query='bitcoin sourcelang:english',mode='timelinetone',format='json',startdatetime=f'{a:%Y%m%d}000000',enddatetime=f'{b:%Y%m%d}235959'),timeout=90)
        if r.status_code==200 and r.text.strip().startswith('{'):
            try:
                d=r.json()['timeline'][0]['data'];json.dump(d,open(p,'w'));return d
            except Exception as e: print('파싱',a,e,r.text[:80])
        else: print(a,r.status_code,r.text[:60].replace('\n',' '));time.sleep(20)
    return None
cur=dt.date(2021,1,1);end=dt.date(2026,10,5);ok=0;bad=[]
while cur<=end:
    nxt=min(cur+dt.timedelta(days=89),end)
    d=chunk(cur,nxt)
    if d: ok+=1;print(cur,nxt,len(d),'점',flush=True)
    else: bad.append(cur)
    cur=nxt+dt.timedelta(days=1)
print('완료 성공',ok,'실패',bad)
