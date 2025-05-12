import logging
import asyncio
import time
import talib
import numpy as np
from iqoptionapi.api import IQOptionAPI
from settings import (
    RSI_INDICATOR, RSI_PERIOD, RSI_MIN, RSI_MAX,
    SMA_INDICATOR, SMA_PERIOD, SMA_MIN, SMA_MAX,
    EMA_INDICATOR, EMA_PERIOD, EMA_MIN, EMA_MAX,
    STOCHASTIC_INDICATOR, STOCHASTIC_K_PERIOD, STOCHASTIC_D_PERIOD,
    MACD_INDICATOR, MACD_FAST_PERIOD, MACD_SLOW_PERIOD, MACD_SIGNAL_PERIOD
)
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

def get_indicator_cache(timeframe: int):
    ttl = timeframe * 5
    return TTLCache(maxsize=100, ttl=ttl)

candle_cache = TTLCache(maxsize=100, ttl=300)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError, asyncio.CancelledError))
)
async def get_candles_with_retry(client: IQOptionAPI, asset: str, timeframe: int, history_size: int):
    try:
        response = client.getcandles(asset, timeframe, history_size)
        candles = response.json()['data'] if response.json().get('data') else []
        return candles
    except Exception as e:
        logger.warning(f"Failed to fetch candles for {asset}: {e}. Retrying...")
        raise

async def calculate_indicators(client: IQOptionAPI, assets: list, timeframe: int = 60) -> dict:
    if not assets:
        logger.debug("No assets provided. Returning empty dictionary.")
        return {}

    indicator_cache = get_indicator_cache(timeframe)
    cache_key = f"{timeframe}_{','.join(sorted(assets))}"
    if cache_key in indicator_cache:
        logger.debug(f"Returning cached indicators for key: {cache_key}")
        return indicator_cache[cache_key]

    indicators_config = []
    if RSI_INDICATOR:
        indicators_config.append(('RSI', {'period': RSI_PERIOD}, RSI_MIN, RSI_MAX, RSI_PERIOD))
    if SMA_INDICATOR:
        indicators_config.append(('SMA', {'period': SMA_PERIOD}, SMA_MIN, SMA_MAX, SMA_PERIOD))
    if EMA_INDICATOR:
        indicators_config.append(('EMA', {'period': EMA_PERIOD}, EMA_MIN, EMA_MAX, EMA_PERIOD))
    if STOCHASTIC_INDICATOR:
        indicators_config.append(('STOCHASTIC', {'k_period': STOCHASTIC_K_PERIOD, 'd_period': STOCHASTIC_D_PERIOD}, float('-inf'), float('inf'), STOCHASTIC_K_PERIOD))
    if MACD_INDICATOR:
        indicators_config.append(('MACD', {'fast_period': MACD_FAST_PERIOD, 'slow_period': MACD_SLOW_PERIOD, 'signal_period': MACD_SIGNAL_PERIOD}, float('-inf'), float('inf'), MACD_SLOW_PERIOD))
    indicators_config.append(('BOLLINGER', {'period': 50, 'deviation': 2}, float('-inf'), float('inf'), 50))

    if not indicators_config:
        logger.warning("No indicators enabled. Returning empty results.")
        return {asset: {} for asset in assets}

    results = {asset: {} for asset in assets}
    semaphore = asyncio.Semaphore(5)

    for asset in assets:
        try:
            max_period = max(period for _, _, _, _, period in indicators_config)
            history_size = max(1800, timeframe * (max_period * 3))
            cache_key_candles = f"{asset}_{timeframe}_{history_size}"
            if cache_key_candles in candle_cache:
                candles = candle_cache[cache_key_candles]
            else:
                candles = await get_candles_with_retry(client, asset, timeframe, history_size)
                candle_cache[cache_key_candles] = candles

            if not candles or len(candles) < max_period:
                logger.warning(f"Insufficient candle data for {asset}. Skipping.")
                continue

            closes = np.array([float(candle['close']) for candle in candles])
            highs = np.array([float(candle['max']) for candle in candles])
            lows = np.array([float(candle['min']) for candle in candles])

            async with semaphore:
                for indicator_name, params, min_val, max_val, period in indicators_config:
                    try:
                        if indicator_name == 'RSI':
                            value = talib.RSI(closes, timeperiod=params['period'])[-1]
                        elif indicator_name == 'SMA':
                            value = talib.SMA(closes, timeperiod=params['period'])[-1]
                        elif indicator_name == 'EMA':
                            value = talib.EMA(closes, timeperiod=params['period'])[-1]
                        elif indicator_name == 'STOCHASTIC':
                            k, d = talib.STOCH(highs, lows, closes, fastk_period=params['k_period'], slowd_period=params['d_period'])
                            value = {'k': k[-1], 'd': d[-1]}
                        elif indicator_name == 'MACD':
                            macd, signal, _ = talib.MACD(closes, fastperiod=params['fast_period'], slowperiod=params['slow_period'], signalperiod=params['signal_period'])
                            value = {'macd': macd[-1], 'signal': signal[-1]}
                        elif indicator_name == 'BOLLINGER':
                            upper, middle, lower = talib.BBANDS(closes, timeperiod=params['period'], nbdevup=params['deviation'], nbdevdn=params['deviation'])
                            value = {'BB_upper': upper[-1], 'BB_lower': lower[-1]}

                        if isinstance(value, dict):
                            if all(v is not None and isinstance(v, (int, float)) for v in value.values()):
                                results[asset][indicator_name] = value
                            else:
                                results[asset][indicator_name] = None
                        else:
                            if isinstance(value, (int, float)) and min_val <= value <= max_val:
                                results[asset][indicator_name] = value
                            else:
                                results[asset][indicator_name] = None

                    except Exception as e:
                        logger.error(f"Error calculating {indicator_name} for {asset}: {e}")
                        results[asset][indicator_name] = None

        except Exception as e:
            logger.error(f"Error processing data for {asset}: {e}")

    indicator_cache[cache_key] = results
    logger.debug(f"Cached indicators for key: {cache_key}")
    return results