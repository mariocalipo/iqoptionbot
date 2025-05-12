import logging
import asyncio
import time
from iqoptionapi.api import IQOptionAPI
from settings import (
    TIMEFRAME, MIN_PAYOUT, ASSETS, SORT_BY, SORT_ORDER,
    RSI_BUY_THRESHOLD, RSI_SELL_THRESHOLD, MACD_INDICATOR,
    INDICATOR_TIMEOUT, STOCHASTIC_BUY_THRESHOLD, STOCHASTIC_SELL_THRESHOLD
)
from indicators import calculate_indicators

logger = logging.getLogger(__name__)

def extract_price(price_data):
    if isinstance(price_data, dict) and 'close' in price_data:
        return float(price_data['close'])
    return None

async def get_realtime_prices(client: IQOptionAPI, assets: list) -> dict:
    prices = {}
    if not assets:
        return prices

    semaphore = asyncio.Semaphore(10)
    async def fetch_price(asset):
        async with semaphore:
            try:
                client.subscribe(asset, int(TIMEFRAME.replace('M', '')))
                await asyncio.sleep(1)  # Aguarda dados do WebSocket
                data = client.candles.get_realtime_candles(asset, int(TIMEFRAME.replace('M', '')))
                price = extract_price(list(data.values())[-1] if data else None)
                if isinstance(price, (int, float)):
                    prices[asset] = price
                else:
                    logger.debug(f"No numeric price for {asset}: {data}")
            except Exception as e:
                logger.warning(f"Failed to fetch price for {asset}: {e}")

    await asyncio.gather(*(fetch_price(asset) for asset in assets))
    return prices

async def list_open_otc_assets(client: IQOptionAPI):
    timeframe = TIMEFRAME if TIMEFRAME in ('1M', '5M') else '1M'
    sort_by = SORT_BY if SORT_BY in ('payout', 'price') else 'payout'
    sort_order = SORT_ORDER if SORT_ORDER in ('asc', 'desc') else 'desc'

    try:
        open_assets = client.getprofile().json()['result']['binary']['open']
        otc_names = [name for name, is_open in open_assets.items() if name.endswith('-OTC') and is_open]
    except Exception as e:
        logger.error(f"Error fetching open assets: {e}")
        return []

    if ASSETS and any(a.strip() for a in ASSETS):
        selected = [a.strip() for a in ASSETS if isinstance(a, str) and a.strip()]
        otc_names = [a for a in selected if a in otc_names]
        logger.info(f"Assets filter applied: {selected}, remaining: {otc_names}")

    candidates = []
    for asset in otc_names:
        try:
            payout_response = client.billing(asset)
            payout = payout_response.json()['result']['payout'] if payout_response.json().get('result') else 0
            if isinstance(payout, (int, float)) and payout >= MIN_PAYOUT:
                candidates.append((asset, payout))
            else:
                logger.debug(f"Skipping {asset}: Payout {payout} below minimum {MIN_PAYOUT}%")
        except Exception as e:
            logger.warning(f"Payout fetch error for {asset}: {e}")

    if not candidates:
        logger.info("No open OTC assets meet the minimum payout criteria.")
        return []

    assets_list = [a for a, _ in candidates]
    prices = await get_realtime_prices(client, assets_list)
    indicators = await asyncio.wait_for(calculate_indicators(client, assets_list), timeout=INDICATOR_TIMEOUT)

    tradable = []
    discard_counts = {'price_invalid': 0, 'missing_indicators': 0, 'invalid_stochastic': 0, 'no_signal': 0}

    for asset, payout in candidates:
        vals = indicators.get(asset, {})
        rsi = vals.get("RSI")
        sma = vals.get("SMA")
        stoch_k = vals.get("STOCHASTIC", {}).get("k")
        stoch_d = vals.get("STOCHASTIC", {}).get("d")
        macd = vals.get("MACD", {}).get("macd")
        signal = vals.get("MACD", {}).get("signal")
        bb_upper = vals.get("BB_upper")
        bb_lower = vals.get("BB_lower")
        price = prices.get(asset)

        if price is None or price < 0.0001:
            logger.warning(f"Skipping {asset}: Invalid price ({price})")
            discard_counts['price_invalid'] += 1
            continue
        if rsi is None or sma is None:
            logger.warning(f"Skipping {asset}: Missing indicators")
            discard_counts['missing_indicators'] += 1
            continue
        if stoch_k is None or stoch_d is None:
            logger.warning(f"Skipping {asset}: Invalid Stochastic")
            discard_counts['invalid_stochastic'] += 1
            continue

        buy = rsi < RSI_BUY_THRESHOLD and stoch_k < STOCHASTIC_BUY_THRESHOLD and \
              (not MACD_INDICATOR or (macd is not None and signal is not None and macd > signal)) and \
              (bb_lower is None or price > bb_lower)
        sell = rsi > RSI_SELL_THRESHOLD and stoch_k > STOCHASTIC_SELL_THRESHOLD and \
               (not MACD_INDICATOR or (macd is not None and signal is not None and macd < signal)) and \
               (bb_upper is None or price < bb_upper)
        if buy or sell:
            tradable.append((asset, payout))
        else:
            discard_counts['no_signal'] += 1

    logger.info(f"Discard summary: {discard_counts}")
    tradable.sort(key=lambda x: x[1] if sort_by == 'payout' else prices.get(x[0], 0), reverse=(sort_order == 'desc'))
    logger.info(f"Tradable assets: {tradable}")
    return tradable