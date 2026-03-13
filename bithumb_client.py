from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from statistics import mean


API_BASE = "https://api.bithumb.com/public"
SSL_CONTEXT = ssl.create_default_context()


class BithumbAPIError(RuntimeError):
    pass


@dataclass
class TickerSnapshot:
    symbol: str
    close_price: float
    opening_price: float
    high_price: float
    low_price: float
    units_traded_24h: float
    acc_trade_value_24h: float
    fluctate_rate_24h: float


@dataclass
class Candle:
    timestamp_ms: int
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float


class BithumbPublicClient:
    def __init__(self, timeout: int = 8) -> None:
        self.timeout = timeout

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict:
        url = f"{API_BASE}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "user-agent": "stock-bithumb-assistant/1.0",
            },
        )
        with urllib.request.urlopen(
            request, timeout=self.timeout, context=SSL_CONTEXT
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

        status = payload.get("status")
        if status not in (None, "0000"):
            raise BithumbAPIError(f"Bithumb API returned status {status}")
        return payload

    def get_all_tickers(self, quote_currency: str = "KRW") -> dict[str, TickerSnapshot]:
        payload = self._get_json(f"/ticker/ALL_{quote_currency}")
        data = payload["data"]
        result: dict[str, TickerSnapshot] = {}

        for symbol, values in data.items():
            if symbol == "date":
                continue
            result[symbol] = TickerSnapshot(
                symbol=symbol,
                close_price=float(values["closing_price"]),
                opening_price=float(values["opening_price"]),
                high_price=float(values["max_price"]),
                low_price=float(values["min_price"]),
                units_traded_24h=float(values["units_traded_24H"]),
                acc_trade_value_24h=float(values["acc_trade_value_24H"]),
                fluctate_rate_24h=float(values["fluctate_rate_24H"]),
            )
        return result

    def get_ticker(self, symbol: str, quote_currency: str = "KRW") -> TickerSnapshot:
        payload = self._get_json(f"/ticker/{symbol}_{quote_currency}")
        values = payload["data"]
        return TickerSnapshot(
            symbol=symbol,
            close_price=float(values["closing_price"]),
            opening_price=float(values["opening_price"]),
            high_price=float(values["max_price"]),
            low_price=float(values["min_price"]),
            units_traded_24h=float(values["units_traded_24H"]),
            acc_trade_value_24h=float(values["acc_trade_value_24H"]),
            fluctate_rate_24h=float(values["fluctate_rate_24H"]),
        )

    def get_candles(
        self,
        symbol: str,
        interval: str = "1m",
        quote_currency: str = "KRW",
        limit: int = 120,
    ) -> list[Candle]:
        payload = self._get_json(f"/candlestick/{symbol}_{quote_currency}/{interval}")
        raw_candles = payload["data"][-limit:]
        candles = [
            Candle(
                timestamp_ms=int(row[0]),
                open_price=float(row[1]),
                close_price=float(row[2]),
                high_price=float(row[3]),
                low_price=float(row[4]),
                volume=float(row[5]),
            )
            for row in raw_candles
        ]
        return candles

    def get_top_symbols_by_value(
        self, symbols: list[str], top_n: int = 4
    ) -> list[TickerSnapshot]:
        tickers = self.get_all_tickers()
        filtered = [tickers[symbol] for symbol in symbols if symbol in tickers]
        return sorted(
            filtered, key=lambda item: item.acc_trade_value_24h, reverse=True
        )[:top_n]


def summarize_intraday(candles: list[Candle]) -> dict[str, float]:
    if not candles:
        raise ValueError("No candles provided")

    closes = [item.close_price for item in candles]
    volumes = [item.volume for item in candles]
    highs = [item.high_price for item in candles]
    lows = [item.low_price for item in candles]
    latest = candles[-1].close_price
    first = candles[0].open_price
    recent_closes = closes[-5:] if len(closes) >= 5 else closes
    recent_volumes = volumes[-5:] if len(volumes) >= 5 else volumes
    base_volumes = volumes[-20:-5] if len(volumes) >= 20 else volumes[:-5]
    average_base_volume = mean(base_volumes) if base_volumes else mean(volumes)

    return {
        "latest_price": latest,
        "session_change_pct": ((latest / first) - 1) * 100 if first else 0.0,
        "range_pct": ((max(highs) / min(lows)) - 1) * 100 if min(lows) else 0.0,
        "recent_momentum_pct": ((recent_closes[-1] / recent_closes[0]) - 1) * 100
        if len(recent_closes) >= 2 and recent_closes[0]
        else 0.0,
        "recent_volume_ratio": (mean(recent_volumes) / average_base_volume)
        if average_base_volume
        else 1.0,
        "high_price": max(highs),
        "low_price": min(lows),
    }
