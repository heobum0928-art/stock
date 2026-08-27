"""코인판 게시판 수집기 — 관찰 전용.

★ 이 봇은 매매에 일절 쓰이지 않는다. 알림도 보내지 않는다. CSV만 쌓는다.
   커뮤니티 심리를 매매 신호로 쓰는 것은 **검증되지 않은 가설**이며,
   검정은 반드시 docs/PREREG_*.md 사전등록을 먼저 쓴 뒤에 한다(CLAUDE.md 5·7항).
   "게시판 보고 감으로 산다"가 되는 순간 지금까지의 규율이 전부 무의미해진다.

수집 방식: 각 게시판 1페이지를 주기적으로 읽어 새 글을 기록하고,
글이 1페이지에서 밀려나면 그때까지 관측한 최대 조회수·추천수를 확정해 CSV에 쓴다.
(글 하나당 CSV 한 줄 — 매 폴링마다 스냅샷을 쌓으면 파일이 감당 안 된다.)

robots.txt 확인(2026-08-27): Disallow는 /inquiry/ 뿐. 목록 페이지 수집은 허용 범위.
예의상 폴링 간격을 넉넉히 두고 게시판당 1페이지만 읽는다.
"""
import csv, json, logging, re, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KST = timezone(timedelta(hours=9))
BOARDS = ["free", "futures", "pnl", "coin_info"]
BASE = "https://coinpan.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
POLL_SEC = 900          # 15분. 게시판당 1페이지 → 시간당 16요청
REQ_GAP = 3.0           # 게시판 간 간격

POSTS_PATH = ROOT / "data" / "coinpan_posts.csv"
STATE_PATH = ROOT / "data" / "coinpan_state.json"
LOG_PATH = ROOT / "logs" / "coinpan_monitor.log"
FIELDS = ["board", "doc_id", "title", "posted", "first_seen", "last_seen",
          "views", "votes", "minutes_on_page1"]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [COINPAN] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger(__name__)

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TITLE_RE = re.compile(r'<td class="title">.*?<a href="/(?P<b>[a-z_]+)/(?P<id>\d{5,})".*?>(?P<t>.*?)</a>', re.S)
TIME_RE = re.compile(r'<td class="time">\s*<span class="number">\s*(.*?)\s*</span>', re.S)
NUM_RE = re.compile(r'<td class="(readed|voted)">\s*<span class="number">\s*(.*?)\s*</span>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    s = TAG_RE.sub("", s)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&nbsp;", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _int(s: str) -> int:
    m = re.search(r"\d+", s.replace(",", ""))
    return int(m.group()) if m else 0


def fetch_board(board: str):
    """1페이지의 일반글 목록. 공지·광고 행은 버린다."""
    r = requests.get(f"{BASE}/{board}", headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    out = []
    for row in ROW_RE.findall(r.text):
        if 'class="notice"' in row or ">AD<" in row or ">공지<" in row:
            continue
        m = TITLE_RE.search(row)
        if not m or m.group("b") != board:
            continue
        title = _clean(m.group("t"))
        if not title:
            continue
        tm = TIME_RE.search(row)
        nums = dict(NUM_RE.findall(row))
        out.append({
            "board": board, "doc_id": m.group("id"), "title": title,
            "posted": _clean(tm.group(1)) if tm else "",
            "views": _int(nums.get("readed", "0")), "votes": _int(nums.get("voted", "0")),
        })
    return out


def flush(rows):
    new = not POSTS_PATH.exists()
    with open(POSTS_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def main():
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    log.info("코인판 수집기 시작 [관찰 전용 — 매매·알림 없음] 게시판 %s | %d초 주기",
             ",".join(BOARDS), POLL_SEC)
    while True:
        try:
            now = time.time()
            seen_now = set()
            for b in BOARDS:
                try:
                    posts = fetch_board(b)
                except Exception as e:
                    log.warning("%s 수집 실패: %s", b, e)
                    time.sleep(REQ_GAP)
                    continue
                if not posts:
                    log.warning("%s 파싱 결과 0건 — 페이지 구조 변경 의심", b)
                for p in posts:
                    key = f"{b}/{p['doc_id']}"
                    seen_now.add(key)
                    st = state.get(key)
                    if st is None:
                        state[key] = {**p, "first_seen": datetime.now(KST).isoformat(),
                                      "last_seen_ts": now}
                    else:
                        st["views"] = max(st.get("views", 0), p["views"])
                        st["votes"] = max(st.get("votes", 0), p["votes"])
                        st["last_seen_ts"] = now
                time.sleep(REQ_GAP)

            # 1페이지에서 밀려난 글 = 확정. 한 줄 쓰고 상태에서 제거.
            done = []
            for key, st in list(state.items()):
                if key in seen_now:
                    continue
                if now - st.get("last_seen_ts", now) < POLL_SEC * 1.5:
                    continue      # 일시적 누락 방지 — 2회 연속 안 보여야 확정
                fs = st.get("first_seen", "")
                mins = round((st.get("last_seen_ts", now) -
                              datetime.fromisoformat(fs).timestamp()) / 60, 1) if fs else ""
                done.append({**st, "last_seen": datetime.fromtimestamp(
                    st.get("last_seen_ts", now), KST).isoformat(), "minutes_on_page1": mins})
                del state[key]
            if done:
                flush(done)
                log.info("확정 %d건 기록 (추적중 %d건)", len(done), len(state))
            STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.error("루프오류: %s", e)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
