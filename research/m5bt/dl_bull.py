"""강세장 구간(2023-01 ~ 2025-06) 5분봉 다운로드 — pq_bull/ 에 저장.

배경(2026-09-02 발견): 기존 pq/ 데이터는 2025-07~2026-07의 **하락장 1년**(BTC -41.3%)뿐이라,
숏 전략의 모든 검증치가 하락장 조건부이고 강세장에서 유지되는지 알 수 없다. 알트 롱은
아예 판정 자체가 불가능하다(하락장에서 롱이 지는 건 당연하므로).
그 앞의 2년 반은 대형 강세장이었다: BTC 2023-01 23,125 → 2025-07 115,764 (+400%).

기존 pq/ 는 건드리지 않고 별도 디렉토리에 받는다 — 두 레짐을 섞지 않고 각각/합쳐서
검증할 수 있게 하기 위함. dl.py의 다운로드 로직을 그대로 재사용한다.
"""
import requests, io, zipfile, json, os, time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

D = os.path.dirname(os.path.abspath(__file__))
BASE = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/5m/{s}-5m-{m}.zip"
MONTHS = [f"{y}-{mm:02d}" for y in (2023, 2024, 2025) for mm in range(1, 13)]
MONTHS = [m for m in MONTHS if "2023-01" <= m <= "2025-06"]   # 기존 pq/(2025-07~)와 안 겹치게
OUT_DIR = os.path.join(D, "pq_bull")
COLS = ["open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "tb", "tbq", "ig"]

syms = json.load(open(os.path.join(D, "all_um_usdt_syms.json")))
os.makedirs(OUT_DIR, exist_ok=True)
sess = requests.Session()


def one(s):
    out = os.path.join(OUT_DIR, f"{s}.npz")
    if os.path.exists(out):
        return (s, -1)
    frames = []
    for m in MONTHS:
        r = None
        for _ in range(3):
            try:
                r = sess.get(BASE.format(s=s, m=m), timeout=60)
                break
            except Exception:
                time.sleep(2); r = None
        if r is None or r.status_code != 200:
            continue          # 그 달에 미상장이면 404 — 정상, 건너뛴다
        try:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = z.read(z.namelist()[0])
            hdr = 0 if raw[:9].decode(errors="replace").startswith("open_time") else None
            df = pd.read_csv(io.BytesIO(raw), header=hdr, names=None if hdr == 0 else COLS)
        except Exception:
            continue
        frames.append(df[["open_time", "open", "high", "low", "close", "quote_volume"]].copy())
    if not frames:
        return (s, 0)
    d = pd.concat(frames, ignore_index=True).astype(
        {"open_time": "int64", "open": "float64", "high": "float64",
         "low": "float64", "close": "float64", "quote_volume": "float64"})
    d = d.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    np.savez_compressed(out, t=d["open_time"].to_numpy(), o=d["open"].to_numpy(),
                        h=d["high"].to_numpy(), l=d["low"].to_numpy(),
                        c=d["close"].to_numpy(), qv=d["quote_volume"].to_numpy())
    return (s, len(d))


if __name__ == "__main__":
    print(f"강세장 구간 다운로드 시작: {MONTHS[0]} ~ {MONTHS[-1]} ({len(MONTHS)}개월), 종목 {len(syms)}개")
    print(f"저장 위치: {OUT_DIR}  (기존 pq/ 는 건드리지 않음)")
    res = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for i, r in enumerate(ex.map(one, syms)):
            res.append(r)
            if i % 50 == 0:
                print(f"  {i}/{len(syms)} {r}", flush=True)
    got = [r for r in res if r[1] > 0]
    skip = [r for r in res if r[1] == -1]
    none = [r for r in res if r[1] == 0]
    print(f"\n완료: 신규 {len(got)}종목 / 기존보유 {len(skip)} / 데이터없음 {len(none)}")
    if got:
        print(f"  평균 봉수 {sum(r[1] for r in got)//len(got):,}")
