from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from bithumb_client import Candle, TickerSnapshot


KST = timezone(timedelta(hours=9), name="KST")


@dataclass
class PositionInput:
    symbol: str
    entry_price: float
    quantity: float
    entry_time: str


@dataclass
class DecisionResult:
    action: str
    headline: str
    reason: str
    current_price: float
    pnl_pct: float
    pnl_krw: float
    peak_price: float
    peak_gain_pct: float
    trail_drawdown_pct: float
    stop_price: float
    take_profit_price: float


@dataclass
class MarketCandidate:
    symbol: str
    score: float
    action: str
    headline: str
    reason: str
    current_price: float
    day_change_pct: float
    hour_change_pct: float
    recent_momentum_pct: float
    range_pct: float
    volume_ratio: float
    stop_price: float
    take_profit_price: float
    entry_band_high: float


def parse_entry_cutoff(entry_time: str) -> datetime:
    hour, minute = [int(part) for part in entry_time.split(":")]
    now = datetime.now(KST)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def select_candles_since_entry(candles: list[Candle], entry_time: str) -> list[Candle]:
    cutoff = parse_entry_cutoff(entry_time)
    selected = [
        candle
        for candle in candles
        if datetime.fromtimestamp(candle.timestamp_ms / 1000, UTC).astimezone(KST) >= cutoff
    ]
    return selected or candles[-1:]


def evaluate_position(
    position: PositionInput,
    current_price: float,
    candles_since_entry: list[Candle],
    recent_momentum_pct: float,
    recent_volume_ratio: float,
    stop_loss_pct: float = 1.2,
    take_profit_pct: float = 1.8,
    trailing_activation_pct: float = 1.4,
    trailing_drawdown_pct: float = 0.7,
) -> DecisionResult:
    peak_price = max(candle.high_price for candle in candles_since_entry)
    pnl_pct = ((current_price / position.entry_price) - 1) * 100
    peak_gain_pct = ((peak_price / position.entry_price) - 1) * 100
    trail_drawdown = ((peak_price / current_price) - 1) * 100 if current_price else 0.0
    pnl_krw = (current_price - position.entry_price) * position.quantity
    stop_price = position.entry_price * (1 - stop_loss_pct / 100)
    take_profit_price = position.entry_price * (1 + take_profit_pct / 100)

    if pnl_pct <= -stop_loss_pct:
        return DecisionResult(
            action="SELL",
            headline="지금 손절",
            reason=f"매수가 대비 {pnl_pct:.2f}% 하락했습니다. 손절 기준 {-stop_loss_pct:.2f}%를 넘었습니다.",
            current_price=current_price,
            pnl_pct=pnl_pct,
            pnl_krw=pnl_krw,
            peak_price=peak_price,
            peak_gain_pct=peak_gain_pct,
            trail_drawdown_pct=trail_drawdown,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    if peak_gain_pct >= trailing_activation_pct and trail_drawdown >= trailing_drawdown_pct:
        return DecisionResult(
            action="SELL",
            headline="지금 팔기",
            reason=(
                f"진입 후 최고 수익률 {peak_gain_pct:.2f}%를 만든 뒤 "
                f"고점 대비 {trail_drawdown:.2f}% 밀렸습니다."
            ),
            current_price=current_price,
            pnl_pct=pnl_pct,
            pnl_krw=pnl_krw,
            peak_price=peak_price,
            peak_gain_pct=peak_gain_pct,
            trail_drawdown_pct=trail_drawdown,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    if pnl_pct >= take_profit_pct and recent_momentum_pct <= 0:
        return DecisionResult(
            action="SELL",
            headline="목표 수익 도달",
            reason=f"수익률 {pnl_pct:.2f}%입니다. 단기 흐름이 둔화돼 익절 우선 구간입니다.",
            current_price=current_price,
            pnl_pct=pnl_pct,
            pnl_krw=pnl_krw,
            peak_price=peak_price,
            peak_gain_pct=peak_gain_pct,
            trail_drawdown_pct=trail_drawdown,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    if pnl_pct >= 1.0 and recent_volume_ratio < 0.95 and recent_momentum_pct <= 0:
        return DecisionResult(
            action="TRIM",
            headline="절반 매도 가능",
            reason="수익 구간이지만 거래량이 줄고 있습니다. 일부 익절 후 남은 물량만 보는 쪽이 안전합니다.",
            current_price=current_price,
            pnl_pct=pnl_pct,
            pnl_krw=pnl_krw,
            peak_price=peak_price,
            peak_gain_pct=peak_gain_pct,
            trail_drawdown_pct=trail_drawdown,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    return DecisionResult(
        action="HOLD",
        headline="아직 보유",
        reason="손절 범위 안에 있고 단기 흐름도 아직 완전히 꺾이지 않았습니다.",
        current_price=current_price,
        pnl_pct=pnl_pct,
        pnl_krw=pnl_krw,
        peak_price=peak_price,
        peak_gain_pct=peak_gain_pct,
        trail_drawdown_pct=trail_drawdown,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
    )


def score_market_candidate(
    symbol: str,
    ticker: TickerSnapshot,
    summary: dict[str, float],
    btc_summary: dict[str, float],
) -> MarketCandidate:
    current_price = summary["latest_price"]
    day_change_pct = ticker.fluctate_rate_24h
    hour_change_pct = summary["session_change_pct"]
    recent_momentum_pct = summary["recent_momentum_pct"]
    range_pct = summary["range_pct"]
    volume_ratio = summary["recent_volume_ratio"]
    btc_support = btc_summary["recent_momentum_pct"]

    score = 0.0
    score += min(max(day_change_pct, -3.0), 4.0) * 1.0
    score += min(max(hour_change_pct, -1.5), 2.2) * 2.5
    score += min(max(recent_momentum_pct, -0.8), 1.0) * 7.0
    score += min(max((volume_ratio - 1.0) * 10, -3.0), 5.0)
    score += min(max((range_pct - 0.7) * 2.5, -2.0), 3.5)

    if symbol != "BTC":
        score += min(max(btc_support, -0.6), 0.8) * 4.5

    stop_price = current_price * 0.988
    take_profit_price = current_price * 1.018
    entry_band_high = current_price * 1.002

    if (
        recent_momentum_pct > 0.10
        and volume_ratio >= 1.03
        and hour_change_pct >= 0
        and range_pct <= 3.5
    ):
        action = "BUY"
        headline = "지금 볼 종목"
        reason = "모멘텀과 거래량이 같이 붙고 있어 오늘 기준으로 가장 낫습니다."
    elif (
        recent_momentum_pct > -0.05
        and volume_ratio >= 0.98
        and hour_change_pct >= -0.2
        and range_pct <= 3.8
    ):
        action = "WATCH"
        headline = "조금 더 기다리기"
        reason = "완전히 나쁘진 않지만 체결이 더 붙는지 확인 후 들어가는 게 낫습니다."
        score -= 2.5
    else:
        action = "SKIP"
        headline = "오늘 제외"
        reason = "굳이 무리해서 들어갈 필요가 없는 흐름입니다."
        score -= 6.0

    if range_pct > 4.0 and recent_momentum_pct < 0:
        action = "SKIP"
        headline = "변동성 과열"
        reason = "변동성만 크고 최근 흐름이 약합니다. 추격 매수 구간이 아닙니다."
        score -= 5.0

    return MarketCandidate(
        symbol=symbol,
        score=score,
        action=action,
        headline=headline,
        reason=reason,
        current_price=current_price,
        day_change_pct=day_change_pct,
        hour_change_pct=hour_change_pct,
        recent_momentum_pct=recent_momentum_pct,
        range_pct=range_pct,
        volume_ratio=volume_ratio,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        entry_band_high=entry_band_high,
    )


def build_market_bias(btc_summary: dict[str, float]) -> tuple[str, str]:
    momentum = btc_summary["recent_momentum_pct"]
    volume_ratio = btc_summary["recent_volume_ratio"]

    if momentum > 0.15 and volume_ratio >= 1.0:
        return (
            "오늘 매매 가능",
            "BTC 흐름이 무너지지 않았습니다. 오늘은 1순위 종목만 짧게 볼 수 있습니다.",
        )
    if momentum < -0.15 and volume_ratio >= 1.0:
        return (
            "오늘 쉬기",
            "BTC가 밀리면서 거래량도 붙고 있습니다. 오늘은 보수적으로 보거나 쉬는 쪽이 낫습니다.",
        )
    return (
        "선별 진입",
        "강한 방향성은 아닙니다. BUY가 뜬 종목만 짧게 보는 보수 운용이 맞습니다.",
    )
