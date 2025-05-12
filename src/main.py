#!/usr/bin/env python3
import logging
import sys
import asyncio
from pathlib import Path
from iqoptionapi.api import IQOptionAPI
from logging.handlers import RotatingFileHandler
import time
from datetime import datetime, timezone

root = Path(__file__).parent
sys.path.insert(0, str(root))

from settings import EMAIL, PASSWORD, IS_DEMO, TRADE_COOLDOWN, TIMEFRAME, STRATEGY
from assets import list_open_otc_assets, extract_price
from trade import execute_trades
from indicators import calculate_indicators

def setup_logging():
    if not logging.getLogger().hasHandlers():
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_format)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)
        log_file = root.parent / "iqoptionbot.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
        file_handler.setFormatter(log_format)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

async def check_connection(client: IQOptionAPI) -> bool:
    logger.debug("Checking connection status...")
    try:
        balance = client.getprofile().json()['result']['balance']
        logger.debug(f"Connection check successful. Current balance: {balance:.2f} USD")
        return True
    except Exception as e:
        logger.warning(f"Connection check failed: {e}")
        return False

async def reconnect(client: IQOptionAPI, max_attempts: int = 5) -> bool:
    logger.info("Attempting to reconnect...")
    for attempt in range(1, max_attempts + 1):
        logger.info(f"Reconnection attempt {attempt}/{max_attempts}...")
        try:
            client.connect()
            if await check_connection(client):
                logger.info("Reconnection successful!")
                balance = client.getprofile().json()['result']['balance']
                account_type = "Demo" if client.getprofile().json()['result']['is_demo'] else "Real"
                logger.info(f"Account balance ({account_type}): {balance:.2f} USD")
                return True
            logger.warning(f"Reconnection attempt {attempt} failed.")
        except Exception as e:
            logger.error(f"Error during reconnection attempt {attempt}: {e}")
        delay = min(5 * (2 ** attempt), 60)
        await asyncio.sleep(delay)
    logger.critical("Failed to reconnect after maximum attempts.")
    return False

async def main():
    setup_logging()
    logger.info("Starting IQ Option trading bot...")

    if not EMAIL or not PASSWORD:
        logger.critical("Email or password not provided in .env file. Exiting.")
        return

    logger.info("Initializing IQ Option client...")
    client = IQOptionAPI("auth.iqoption.com", EMAIL, PASSWORD)
    client.connect()
    client.changebalance("PRACTICE" if IS_DEMO else "REAL")

    if not await check_connection(client):
        logger.critical("Could not establish initial connection. Exiting.")
        return

    balance = client.getprofile().json()['result']['balance']
    account_type = "Demo" if client.getprofile().json()['result']['is_demo'] else "Real"
    logger.info(f"Account balance ({account_type}): {balance:.2f} USD")
    logger.info("-" * 50)

    logger.info("Entering main trading cycle loop.")
    while True:
        start_time_cycle = time.time()
        utc_hour = datetime.now(timezone.utc).hour
        if 22 <= utc_hour <= 2:
            logger.info("Low liquidity period (22h-2h UTC). Pausing for 1 hour.")
            await asyncio.sleep(3600)
            continue

        logger.info("-" * 50)
        logger.info("Starting new trading cycle...")
        logger.info(f"Active trading strategy: {STRATEGY.upper()}")

        try:
            if not await check_connection(client):
                logger.warning("Connection lost. Attempting to reconnect...")
                if not await reconnect(client):
                    logger.critical("Failed to reconnect. Exiting.")
                    return

            logger.info("Listing and filtering open OTC assets...")
            open_assets_details = await list_open_otc_assets(client)
            assets_for_trade = [asset for asset, _ in open_assets_details]
            payout_map = {asset: payout for asset, payout in open_assets_details}

            if not assets_for_trade:
                logger.info("No open OTC assets meet payout or trading criteria.")
            else:
                logger.debug(f"Assets for trade: {assets_for_trade}")
                initial_indicators_log = await calculate_indicators(client, assets_for_trade)
                initial_prices_log = {}
                for asset in assets_for_trade:
                    client.subscribe(asset, int(TIMEFRAME.replace('M', '')))
                    await asyncio.sleep(1)  # Aguarda dados do WebSocket
                    price_data = client.candles.get_realtime_candles(asset, int(TIMEFRAME.replace('M', '')))
                    price = extract_price(list(price_data.values())[-1] if price_data else None)
                    initial_prices_log[asset] = price if price is not None else "N/A"

                logger.info(f"--- Final list of assets for trade execution ({len(assets_for_trade)}) ---")
                for asset in assets_for_trade:
                    payout = payout_map.get(asset, "N/A")
                    price = initial_prices_log.get(asset, "N/A")
                    indicator_values_log = initial_indicators_log.get(asset, {})
                    indicator_str = ", ".join(f"{ind}: {val:.5f}" if isinstance(val, (int, float)) else f"{ind}: N/A" for ind, val in indicator_values_log.items())
                    logger.info(f"    - {asset}: Payout {payout}%, Price: {price}, Indicators: [{indicator_str}]")
                logger.info("---------------------------------------------------")

                logger.info("Executing trading logic...")
                await execute_trades(client, assets_for_trade, initial_indicators_log)

            if not await check_connection(client):
                logger.warning("Connection lost. Attempting to reconnect...")
                if not await reconnect(client):
                    logger.critical("Failed to reconnect. Exiting.")
                    return

        except Exception as e:
            logger.error(f"Unexpected error in trading cycle: {e}")

        end_time_cycle = time.time()
        cycle_duration = end_time_cycle - start_time_cycle
        wait_time_needed = max(0, TRADE_COOLDOWN - cycle_duration)

        if wait_time_needed > 0:
            logger.info(f"Trading cycle completed in {cycle_duration:.2f} seconds.")
            logger.info(f"Waiting {wait_time_needed:.2f} seconds before next cycle.")
            await asyncio.sleep(wait_time_needed)

if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually by user.")
    except Exception as e:
        logger.critical(f"Fatal error during bot execution: {e}")