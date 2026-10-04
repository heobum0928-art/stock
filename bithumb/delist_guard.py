"""상장폐지 공지 직후 코인 숏 차단 (2026-10-03).

근거: 상장폐지 공지가 난 코인은 투기성 급등(숏 스퀴즈)이 잦다. 모의 연구(#14: 공지 후 선물 숏 68건 중 +100% 이상 급등 4건,
평균 -17.6%)와 실거래(HFT 숏 1건 -112 USDT, 전체 손실의 36%, 공지 당일 진입)에서 독립적으로 확인됐다.

동작: 바이낸스 공개 공지 API(카탈로그 161, 인증 불필요)를 6시간마다 받아 공지 후 BLOCK_DAYS일 이내 코인을 차단한다.
fail-open: 조회 실패 시 마지막 캐시를 쓰고, 캐시도 없으면 차단하지 않는다(API 장애로 봇이 멈추지 않게).
주문·설정은 건드리지 않는다. 진입 여부만 판단한다.
"""
import json, re, time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "delist_blocklist.json"
URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
BLOCK_DAYS = 30
# ★ 2026-10-04: 그림자 모드. 급등 숏 8,801건 중 공지 후 30일 이내 117건이 오히려 평균 +5.81% (나머지 -2.09%, 로그 10-04 (2)) —
#   차단 근거가 뒤집혀 실제 차단은 끄고 "차단했을 건"만 data/delist_guard_shadow.csv에 기록한다. 되돌리려면 True.
ENABLED = False
REFRESH_SEC = 6 * 3600
_STOP = {"USDT", "USDC", "BUSD", "FDUSD", "BTC", "ETH", "BNB", "AND", "THE", "WILL", "ON", "SPOT", "MARGIN", "FUTURES",
         "PERPETUAL", "CONTRACT", "CONTRACTS", "TOKEN", "TOKENS", "DELIST", "REMOVAL", "TRADING", "PAIRS", "NOTICE", "OF",
         "LOANS", "UAH", "USDⓈ-M", "USD", "M"}


def _tokens(title: str):
    """제목에서 코인 심볼 추출. 'Binance Will Delist A, B on 2026-..' / 'Futures Will Delist USDⓈ-M AERGOUSDT Perpetual ..'"""
    if "Delist" not in title:
        return []
    out = []
    for w in re.split(r"[ ,()/]+", title):
        if not w or w != w.upper() or not re.fullmatch(r"[A-Z0-9]{2,15}", w):
            continue
        for suf in ("USDT", "USDC", "BUSD"):
            if w.endswith(suf) and len(w) > len(suf):
                w = w[: -len(suf)]
                break
        if w in _STOP or re.fullmatch(r"\d+", w):
            continue
        out.append(w)
    return out


def _fetch():
    arts = []
    for page in range(1, 4):
        r = requests.get(URL, params=dict(type=1, catalogId=161, pageNo=page, pageSize=50), timeout=10).json()
        cs = r["data"]["catalogs"]
        if not cs or not cs[0]["articles"]:
            break
        arts += cs[0]["articles"]
    block = {}
    now = time.time()
    for a in arts:
        age_days = (now - a["releaseDate"] / 1000) / 86400
        if age_days > BLOCK_DAYS:
            continue
        for t in _tokens(a["title"]):
            block[t] = max(block.get(t, 0), a["releaseDate"] / 1000)
    return block


def _load():
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        return d.get("ts", 0), d.get("coins", {})
    except Exception:
        return 0, {}


def blocked_coins() -> dict:
    """{코인: 공지 시각(epoch초)} — 차단 대상. 실패 시 캐시, 캐시도 없으면 빈 dict."""
    ts, coins = _load()
    if time.time() - ts > REFRESH_SEC:
        try:
            coins = _fetch()
            CACHE.write_text(json.dumps({"ts": time.time(), "coins": coins}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    now = time.time()
    return {c: t for c, t in coins.items() if (now - t) / 86400 <= BLOCK_DAYS}


def _shadow_log(coin: str, ann_ts: float) -> None:
    try:
        f = ROOT / "data" / "delist_guard_shadow.csv"
        new = not f.exists()
        with open(f, "a", encoding="utf-8") as fh:
            if new:
                fh.write("time_utc,coin,announced_utc,days_since_announce"+chr(10))
            now = time.time()
            fh.write(f"{datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds')},{coin},{datetime.fromtimestamp(ann_ts, timezone.utc).isoformat(timespec='seconds')},{(now-ann_ts)/86400:.1f}"+chr(10))
    except Exception:
        pass


def is_delist_blocked(coin: str) -> bool:
    try:
        ann = blocked_coins().get(coin.upper())
        if ann is None:
            return False
        if ENABLED:
            return True
        _shadow_log(coin.upper(), ann)  # 그림자 모드: 차단하지 않고 기록만
        return False
    except Exception:
        return False
