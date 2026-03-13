from __future__ import annotations

import hashlib
import html
import os
import secrets
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from bithumb_client import BithumbAPIError, BithumbPublicClient, summarize_intraday
from news_client import fetch_google_news
from strategy import (
    PositionInput,
    build_market_bias,
    evaluate_position,
    score_market_candidate,
    select_candles_since_entry,
)


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
CANDIDATE_SYMBOLS = [
    "BTC",
    "ETH",
    "XRP",
    "SOL",
    "ADA",
    "DOGE",
    "LINK",
    "AVAX",
    "TRX",
    "HBAR",
    "DOT",
    "SUI",
    "ATOM",
    "UNI",
    "APT",
]
POSITION_SYMBOLS = ["BTC", "ETH", "XRP", "SOL", "ADA", "DOGE", "LINK", "AVAX", "TRX", "HBAR"]
MIN_TRADE_VALUE_KRW = 3_000_000_000
KST = timezone(timedelta(hours=9), name="KST")
SESSION_COOKIE = "night_trader_session"


def format_krw(value: float) -> str:
    return f"{value:,.0f} KRW"


def format_pct(value: float) -> str:
    return f"{value:.2f}%"


def get_dashboard_password() -> str | None:
    value = os.getenv("DASHBOARD_PASSWORD", "").strip()
    return value or None


def make_session_token(password: str) -> str:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return digest[:32]


def is_authenticated(handler: BaseHTTPRequestHandler) -> bool:
    password = get_dashboard_password()
    if not password:
        return True

    raw_cookie = handler.headers.get("Cookie", "")
    jar = cookies.SimpleCookie()
    jar.load(raw_cookie)
    session_cookie = jar.get(SESSION_COOKIE)
    if not session_cookie:
        return False
    return secrets.compare_digest(session_cookie.value, make_session_token(password))


def render_login_page(error_message: str = "") -> str:
    error_block = f"<div class='error'>{html.escape(error_message)}</div>" if error_message else ""
    return f"""
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Bithumb Night Trader Login</title>
      <style>
        body {{
          margin: 0;
          min-height: 100vh;
          display: grid;
          place-items: center;
          background: linear-gradient(180deg, #fbf7ef 0%, #f4eedf 100%);
          font-family: Georgia, "Times New Roman", serif;
          color: #1c1a16;
        }}
        .card {{
          width: min(92vw, 420px);
          padding: 28px;
          border-radius: 20px;
          background: #fffaf0;
          border: 1px solid #d8ccb5;
          box-shadow: 0 14px 28px rgba(53, 41, 22, .08);
        }}
        h1 {{ margin: 0 0 12px; }}
        p {{ color: #726b5f; line-height: 1.5; }}
        form {{ display: grid; gap: 12px; margin-top: 18px; }}
        input, button {{
          width: 100%;
          padding: 12px 14px;
          border-radius: 12px;
          border: 1px solid #d8ccb5;
          font-size: 16px;
        }}
        button {{
          cursor: pointer;
          background: #1c1a16;
          color: white;
        }}
        .error {{
          margin-top: 14px;
          padding: 12px 14px;
          border-radius: 14px;
          background: #fff0eb;
          border: 1px solid #efc2b7;
        }}
      </style>
    </head>
    <body>
      <div class="card">
        <h1>Bithumb Night Trader</h1>
        <p>외부 접속용 대시보드입니다. 비밀번호를 입력해야 열립니다.</p>
        {error_block}
        <form method="post" action="/login">
          <input type="password" name="password" placeholder="비밀번호">
          <button type="submit">로그인</button>
        </form>
      </div>
    </body>
    </html>
    """


def render_position_panel(
    client: BithumbPublicClient,
    selected_symbol: str,
    entry_price_text: str,
    quantity_text: str,
    entry_time: str,
) -> str:
    if not entry_price_text or not quantity_text:
        return """
        <section class="card">
          <div class="eyebrow">매도 시점</div>
          <h2>아직 안 샀다면</h2>
          <p>매수가와 수량을 넣으면 지금 팔지, 더 들고 갈지 바로 보여줍니다.</p>
        </section>
        """

    candles = client.get_candles(selected_symbol, interval="1m", limit=180)
    summary = summarize_intraday(candles)
    position = PositionInput(
        symbol=selected_symbol,
        entry_price=float(entry_price_text),
        quantity=float(quantity_text),
        entry_time=entry_time,
    )
    candles_since_entry = select_candles_since_entry(candles, entry_time)
    decision = evaluate_position(
        position=position,
        current_price=summary["latest_price"],
        candles_since_entry=candles_since_entry,
        recent_momentum_pct=summary["recent_momentum_pct"],
        recent_volume_ratio=summary["recent_volume_ratio"],
    )
    return f"""
    <section class="card decision {decision.action.lower()}">
      <div class="eyebrow">매도 시점</div>
      <h2>{html.escape(decision.headline)}</h2>
      <p>{html.escape(decision.reason)}</p>
      <div class="metric-grid">
        <div><span>현재가</span><strong>{format_krw(decision.current_price)}</strong></div>
        <div><span>수익률</span><strong>{format_pct(decision.pnl_pct)}</strong></div>
        <div><span>손절가</span><strong>{format_krw(decision.stop_price)}</strong></div>
        <div><span>익절가</span><strong>{format_krw(decision.take_profit_price)}</strong></div>
      </div>
    </section>
    """


def build_dashboard(params: dict[str, list[str]]) -> str:
    client = BithumbPublicClient()
    now = datetime.now(KST)
    error_message = ""

    selected_symbol = params.get("symbol", ["BTC"])[0]
    entry_price = params.get("entry_price", [""])[0]
    quantity = params.get("quantity", [""])[0]
    entry_time = params.get("entry_time", [now.strftime("%H:%M")])[0]

    bias_title = "정보 수집 대기"
    bias_reason = "시장 데이터를 아직 불러오지 못했습니다."
    quick_action = "잠시 대기"
    quick_reason = "추천 데이터를 아직 불러오지 못했습니다."
    top_symbol_card = "<section class='card'><div class='eyebrow'>종목 선택</div><h2>오늘 볼 종목 없음</h2><p>데이터를 아직 불러오지 못했습니다.</p></section>"
    compare_cards = ""
    news_html = "<li>뉴스를 불러오지 못했습니다.</li>"
    position_html = "<section class='card'><div class='eyebrow'>매도 시점</div><h2>정보 대기</h2><p>매수가를 넣으면 계산됩니다.</p></section>"

    try:
        tickers = client.get_all_tickers()
        summaries = {}
        available_symbols: list[str] = []
        for symbol in CANDIDATE_SYMBOLS:
            ticker = tickers.get(symbol)
            if not ticker or ticker.acc_trade_value_24h < MIN_TRADE_VALUE_KRW:
                continue
            try:
                candles = client.get_candles(symbol, interval="1m", limit=60)
                summaries[symbol] = summarize_intraday(candles)
                available_symbols.append(symbol)
            except (BithumbAPIError, OSError, ValueError):
                continue

        if "BTC" not in summaries:
            raise ValueError("BTC market data unavailable")

        btc_summary = summaries["BTC"]
        bias_title, bias_reason = build_market_bias(btc_summary)

        candidates = [
            score_market_candidate(symbol, tickers[symbol], summaries[symbol], btc_summary)
            for symbol in available_symbols
        ]
        candidates.sort(key=lambda item: item.score, reverse=True)
        top = candidates[0]

        if top.action == "BUY":
            quick_action = f"지금 매수 후보: {top.symbol}"
            quick_reason = "매수 상단 아래에서만 들어가고 손절가를 먼저 확인하면 됩니다."
        elif top.action == "WATCH":
            quick_action = f"지금 대기: {top.symbol}"
            quick_reason = "이 종목은 보고는 있되 지금 바로 사는 구간은 아닙니다."
        else:
            quick_action = "오늘은 쉬기"
            quick_reason = "전체적으로 억지로 들어갈 자리가 아닙니다."

        top_symbol_card = f"""
        <section class="card primary {top.action.lower()}">
          <div class="eyebrow">종목 선택</div>
          <h2>{top.symbol}</h2>
          <div class="hero-price">{format_krw(top.current_price)}</div>
          <div class="badge {top.action.lower()}">{top.action}</div>
          <p>{top.reason}</p>
          <div class="metric-grid">
            <div><span>매수 상단</span><strong>{format_krw(top.entry_band_high)}</strong></div>
            <div><span>손절가</span><strong>{format_krw(top.stop_price)}</strong></div>
            <div><span>익절가</span><strong>{format_krw(top.take_profit_price)}</strong></div>
            <div><span>최근 5분</span><strong>{format_pct(top.recent_momentum_pct)}</strong></div>
          </div>
        </section>
        """

        compare_cards = "".join(
            [
                f"""
                <article class="compare-card {candidate.action.lower()}">
                  <div class="compare-top">
                    <strong>{candidate.symbol}</strong>
                    <span>{candidate.action}</span>
                  </div>
                  <div class="compare-row"><span>현재가</span><strong>{format_krw(candidate.current_price)}</strong></div>
                  <div class="compare-row"><span>매수 상단</span><strong>{format_krw(candidate.entry_band_high)}</strong></div>
                  <div class="compare-row"><span>손절가</span><strong>{format_krw(candidate.stop_price)}</strong></div>
                  <div class="compare-row"><span>익절가</span><strong>{format_krw(candidate.take_profit_price)}</strong></div>
                </article>
                """
                for candidate in candidates
            ]
        )

        news_items = fetch_google_news("crypto OR bitcoin OR ethereum", limit=3)
        news_html = "".join(
            [
                f"<li><a href='{html.escape(item.link)}' target='_blank' rel='noreferrer'>{html.escape(item.title)}</a></li>"
                for item in news_items
            ]
        )

        position_html = render_position_panel(
            client=client,
            selected_symbol=selected_symbol,
            entry_price_text=entry_price,
            quantity_text=quantity,
            entry_time=entry_time,
        )
    except (BithumbAPIError, OSError, ValueError) as error:
        error_message = f"<div class='error'>데이터를 불러오지 못했습니다: {html.escape(str(error))}</div>"

    symbol_options = "".join(
        [
            f"<option value='{symbol}' {'selected' if symbol == selected_symbol else ''}>{symbol}</option>"
            for symbol in POSITION_SYMBOLS
        ]
    )

    return f"""
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
      <meta http-equiv="refresh" content="30">
      <title>Bithumb Night Trader</title>
      <style>
        :root {{
          --bg: #f4eedf;
          --panel: rgba(255, 250, 240, 0.92);
          --ink: #1c1a16;
          --muted: #726b5f;
          --line: #d8ccb5;
          --buy: #a8421f;
          --watch: #a97a17;
          --skip: #45645d;
        }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          color: var(--ink);
          font-family: Georgia, "Times New Roman", serif;
          background:
            radial-gradient(circle at top right, rgba(168,66,31,.12), transparent 32%),
            linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
        }}
        a {{ color: inherit; }}
        .wrap {{
          max-width: 760px;
          margin: 0 auto;
          padding: 14px 12px 28px;
        }}
        .card, .compare-card {{
          background: var(--panel);
          border: 1px solid var(--line);
          border-radius: 20px;
          padding: 16px;
          box-shadow: 0 12px 24px rgba(53, 41, 22, .08);
          backdrop-filter: blur(8px);
        }}
        .stack {{
          display: grid;
          gap: 12px;
        }}
        .eyebrow {{
          font-size: 11px;
          letter-spacing: .14em;
          text-transform: uppercase;
          color: var(--muted);
          margin-bottom: 8px;
        }}
        h1, h2, h3 {{
          margin: 0 0 8px;
        }}
        h1 {{
          font-size: 28px;
        }}
        h2 {{
          font-size: 24px;
        }}
        p {{
          margin: 0;
          line-height: 1.45;
        }}
        .sub, .stamp {{
          color: var(--muted);
        }}
        .stamp {{
          margin-top: 10px;
          font-size: 13px;
        }}
        .hero-price {{
          font-size: 30px;
          margin: 2px 0 10px;
        }}
        .badge {{
          display: inline-block;
          padding: 7px 12px;
          border-radius: 999px;
          font-size: 13px;
          color: white;
          margin-bottom: 10px;
        }}
        .badge.buy {{ background: var(--buy); }}
        .badge.watch {{ background: var(--watch); }}
        .badge.skip {{ background: var(--skip); }}
        .primary.buy {{ border-color: rgba(168,66,31,.45); }}
        .primary.watch {{ border-color: rgba(169,122,23,.55); }}
        .primary.skip {{ border-color: rgba(69,100,93,.45); }}
        .decision.sell {{ border-color: rgba(181,58,45,.45); }}
        .decision.trim {{ border-color: rgba(169,122,23,.55); }}
        .decision.hold {{ border-color: rgba(35,106,90,.45); }}
        .signal-hero {{
          display: grid;
          gap: 10px;
        }}
        .signal-big {{
          font-size: 30px;
          line-height: 1.1;
        }}
        .metric-grid {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
          margin-top: 14px;
        }}
        .metric-grid div {{
          background: rgba(255,255,255,.62);
          border: 1px solid rgba(216,204,181,.85);
          border-radius: 14px;
          padding: 10px;
        }}
        .metric-grid span {{
          display: block;
          color: var(--muted);
          font-size: 12px;
          margin-bottom: 4px;
        }}
        .metric-grid strong {{
          font-size: 17px;
        }}
        .compare-list {{
          display: grid;
          gap: 10px;
        }}
        .compare-top {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 10px;
        }}
        .compare-top span {{
          font-size: 13px;
          color: var(--muted);
        }}
        .compare-row {{
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 6px 0;
          border-top: 1px solid rgba(216,204,181,.65);
        }}
        .compare-row:first-of-type {{
          border-top: 0;
          padding-top: 0;
        }}
        .compare-row span {{
          color: var(--muted);
          font-size: 13px;
        }}
        form {{
          display: grid;
          gap: 10px;
          margin-top: 12px;
        }}
        label {{
          display: grid;
          gap: 5px;
          color: var(--muted);
          font-size: 13px;
        }}
        input, select, button {{
          width: 100%;
          padding: 12px 14px;
          border: 1px solid var(--line);
          border-radius: 12px;
          font-size: 16px;
          background: #fffdf7;
        }}
        button {{
          cursor: pointer;
          background: var(--ink);
          color: white;
        }}
        .news {{
          display: grid;
          gap: 10px;
          padding-left: 18px;
          margin: 0;
        }}
        .error {{
          margin-top: 12px;
          padding: 12px 14px;
          border-radius: 14px;
          background: #fff0eb;
          border: 1px solid #efc2b7;
        }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="stack">
          <section class="card">
            <h1>Bithumb Night Trader</h1>
            <p class="sub">모바일에서 한 화면씩 바로 판단할 수 있게 줄였습니다.</p>
            <div class="stamp">기준 시각: {now.strftime("%Y-%m-%d %H:%M:%S KST")} · 30초 자동 새로고침</div>
            {error_message}
          </section>

          <section class="card signal-hero">
            <div class="eyebrow">지금 행동</div>
            <div class="signal-big">{html.escape(quick_action)}</div>
            <p>{html.escape(quick_reason)}</p>
          </section>

          <section class="card">
            <div class="eyebrow">시장 상태</div>
            <h2>{html.escape(bias_title)}</h2>
            <p>{html.escape(bias_reason)}</p>
          </section>

          {top_symbol_card}

          <section class="card">
            <div class="eyebrow">종목 비교</div>
            <div class="compare-list">{compare_cards}</div>
          </section>

          <section class="card">
            <div class="eyebrow">이미 샀다면</div>
            <h2>매도 시점 확인</h2>
            <form method="get" action="/">
              <label>
                종목
                <select name="symbol">{symbol_options}</select>
              </label>
              <label>
                매수가
                <input type="number" step="0.0001" name="entry_price" value="{html.escape(entry_price)}" placeholder="예: 128500000">
              </label>
              <label>
                수량
                <input type="number" step="0.00000001" name="quantity" value="{html.escape(quantity)}" placeholder="예: 0.01">
              </label>
              <label>
                매수 시각
                <input type="time" name="entry_time" value="{html.escape(entry_time)}">
              </label>
              <button type="submit">매도 시점 보기</button>
            </form>
          </section>

          {position_html}

          <section class="card">
            <div class="eyebrow">오늘 뉴스 3개</div>
            <ul class="news">{news_html}</ul>
          </section>
        </div>
      </div>
    </body>
    </html>
    """


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/logout":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
            )
            self.end_headers()
            return

        if not is_authenticated(self):
            body = render_login_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        params = parse_qs(parsed.query)
        body = build_dashboard(params).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/login":
            self.send_response(404)
            self.end_headers()
            return

        password = get_dashboard_password()
        if not password:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(payload)
        submitted_password = form.get("password", [""])[0]

        if not secrets.compare_digest(submitted_password, password):
            body = render_login_page("비밀번호가 맞지 않습니다.").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            (
                f"{SESSION_COOKIE}={make_session_token(password)}; Path=/; "
                "HttpOnly; SameSite=Lax"
            ),
        )
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def get_bind_host() -> str:
    return os.getenv("HOST", DEFAULT_HOST)


def get_bind_port() -> int:
    return int(os.getenv("PORT", str(DEFAULT_PORT)))


def run_server(host: str | None = None, port: int | None = None) -> None:
    bind_host = host or get_bind_host()
    bind_port = port or get_bind_port()
    httpd = HTTPServer((bind_host, bind_port), DashboardHandler)
    print(f"Serving dashboard on http://{bind_host}:{bind_port}")
    httpd.serve_forever()
