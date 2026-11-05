import logging

logger = logging.getLogger(__name__)


def calculate_rvol(current_volume, historical_volumes):
    if not historical_volumes or len(historical_volumes) < 5:
        return 1.0
    avg_volume = sum(historical_volumes) / len(historical_volumes)
    return current_volume / avg_volume if avg_volume > 0 else 1.0


def check_min_volatility(current_range, historical_ranges, min_ratio):
    if not historical_ranges or len(historical_ranges) < 5:
        return True
    avg_range = sum(historical_ranges) / len(historical_ranges)
    return current_range >= (avg_range * min_ratio) if avg_range > 0 else True


def check_direction_reset(last_trade_direction, current_signal_direction, last_trade_candle_time, candles, bb_length):
    if last_trade_direction != current_signal_direction:
        return True
    if last_trade_candle_time == 0:
        return True

    closed_candles = candles[:-1] if len(candles) > 1 else []
    post_trade_candles = [c for c in closed_candles if c['time'] >= last_trade_candle_time]

    if len(post_trade_candles) == 0:
        return False

    for i, candle in enumerate(closed_candles):
        if candle['time'] >= last_trade_candle_time:
            slice_end = i + 1
            slice_start = max(0, slice_end - bb_length)
            period_closes = [c['close'] for c in candles[slice_start:slice_end]]

            if len(period_closes) < bb_length:
                continue

            candle_sma = sum(period_closes) / bb_length

            if current_signal_direction == "Buy":
                if candle['close'] > candle_sma:
                    return True
            elif current_signal_direction == "Sell":
                if candle['close'] < candle_sma:
                    return True

    return False
