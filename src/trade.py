import logging
import asyncio
import time
import csv
from datetime import datetime
from iqoptionapi.api import IQOptionAPI
from settings import (
    TRADE_ENABLED, TRADE_PERCENTAGE, TRADE_PERCENTAGE_MIN, TRADE_PERCENTAGE_MAX,
    TRADE_DURATION, RSI_BUY_THRESHOLD, RSI_SELL_THRESHOLD, TRADE_COOLDOWN,
    DAILY_LOSS_LIMIT, CONSECUTIVE_LOSSES_THRESHOLD, CONSECUTIVE_WINS_THRESHOLD,
    MACD_INDICATOR, STRATEGY, TIMEFRAME, STOCHASTIC_BUY_THRESHOLD, STOCHASTIC_SELL_THRESHOLD
)
from assets import extract_price
from indicators import calculate_indicators

logger = logging.getLogger(__name__)

class TradingState:
    def __init__(self):
        self.open_orders = []
        self.last_trade_time = {}
        self.daily_loss = 0.0
        self.initial_daily_balance = 0.0
        self.last_reset_time = None
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.current_trade_percentage = TRADE_PERCENTAGE

    def reset_daily(self, balance: float, current_time: int):
        self.daily_loss = 0.0
        self.initial_daily_balance = balance
        self.last_reset_time = current_time
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.current_trade_percentage = TRADE_PERCENTAGE
        logger.info(f"Daily reset: Initial balance {self.initial_daily_balance:.2f} USD.")

    def add_order(self, order_details: dict):
        self.open_orders.append(order_details)
        logger.debug(f"Added order {order_details.get('id')}.")

    def remove_order(self, order: dict):
        try:
            self.open_orders.remove(order)
            logger.debug(f"Removed order ID {order.get('id')}.")
        except ValueError:
            logger.warning(f"Failed to remove order ID {order.get('id')}.")

    def update_trade_time(self, asset: str, current_time: int):
        self.last_trade_time[asset] = current_time

    def update_loss(self, amount: float):
        self.daily_loss += amount
        self.consecutive_losses += 1
        self.consecutive_wins = 0

    def update_win(self, profit: float):
        self.daily_loss -= profit
        self.consecutive_wins += 1
        self.consecutive_losses = 0

    def adjust_trade_percentage(self):
        old = self.current_trade_percentage
        if self.consecutive_losses >= CONSECUTIVE_LOSSES_THRESHOLD:
            self.current_trade_percentage = max(TRADE_PERCENTAGE_MIN, old * 0.3)
        elif self.consecutive_wins >= CONSECUTIVE_WINS_THRESHOLD:
            self.current_trade_percentage = min(TRADE_PERCENTAGE_MAX, old * 1.2)
        else:
            self.current_trade_percentage = TRADE_PERCENTAGE
        if self.current_trade_percentage != old:
            logger.info(f"Trade percentage adjusted from {old:.2f}% to {self.current_trade_percentage:.2f}%")

    def check_daily_loss_limit(self, balance: float) -> bool:
        if self.initial_daily_balance > 0:
            loss_pct = (self.daily_loss / self.initial_daily_balance) * 100
            if loss_pct >= DAILY_LOSS_LIMIT or self.consecutive_losses >= 3:
                logger.warning(f"Stopping: Loss {loss_pct:.2f}% >= {DAILY_LOSS_LIMIT}% or {self.consecutive_losses} losses")
                self.current_trade_percentage = max(TRADE_PERCENTAGE_MIN, self.current_trade_percentage * 0.3)
                return False
        return True

trading_state = TradingState()

def is_trade_signal_trend(indicators, price):
    rsi = indicators.get("RSI")
    sma = indicators.get("SMA")
    stoch_k = indicators.get("STOCHASTIC", {}).get("k")
    stoch_d = indicators.get("STOCHASTIC", {}).get("d")
    macd = indicators.get("MACD", {}).get("macd")
    signal = indicators.get("MACD", {}).get("signal")
    bb_upper = indicators.get("BB_upper")
    bb_lower = indicators.get("BB_lower")

    if None in (rsi, sma, stoch_k, stoch_d, bb_upper, bb_lower):
        return None
    if MACD_INDICATOR and (macd is None or signal is None):
        return None

    if MACD_INDICATOR:
        if rsi < RSI_BUY_THRESHOLD and stoch_k < STOCHASTIC_BUY_THRESHOLD and price >= sma * 0.99 and price > bb_lower and macd > signal:
            return "call"
        if rsi > RSI_SELL_THRESHOLD and stoch_k > STOCHASTIC_SELL_THRESHOLD and price < bb_upper and macd < signal:
            return "put"
    else:
        if rsi < RSI_BUY_THRESHOLD and stoch_k < STOCHASTIC_BUY_THRESHOLD and price >= sma * 0.99 and price > bb_lower:
            return "call"
        if rsi > RSI_SELL_THRESHOLD and stoch_k > STOCHASTIC_SELL_THRESHOLD and price < bb_upper:
            return "put"
    return None

def is_trade_signal_reversal(indicators, price):
    rsi = indicators.get("RSI")
    stoch_k = indicators.get("STOCHASTIC", {}).get("k")
    if rsi is None or stoch_k is None:
        return None
    if rsi <= 20 and stoch_k <= 20:
        return "call"
    if rsi >= 80 and stoch_k >= 80:
        return "put"
    return None

def is_trade_signal_breakout(indicators, price):
    sma = indicators.get("SMA")
    ema = indicators.get("EMA")
    if sma is None or ema is None:
        return None
    if price > sma and price > ema:
        return "call"
    if price < sma and price < ema:
        return "put"
    return None

def get_signal_for_strategy(strategy, indicators, price):
    if strategy == "trend":
        return is_trade_signal_trend(indicators, price)
    if strategy == "reversal":
        return is_trade_signal_reversal(indicators, price)
    if strategy == "breakout":
        return is_trade_signal_breakout(indicators, price)
    logger.warning(f"Unknown strategy: {strategy}")
    return None

async def execute_trades(client: IQOptionAPI, assets: list, indicators: dict):
    if not TRADE_ENABLED or not assets:
        logger.debug("Trade execution skipped: TRADE_ENABLED is False or no assets.")
        return

    now = int(time.time())
    if trading_state.last_reset_time is None or (now - trading_state.last_reset_time) >= 86400:
        balance = client.getprofile().json()['result']['balance']
        trading_state.reset_daily(balance, now)

    to_remove = []
    for order in trading_state.open_orders:
        try:
            asset = order['asset']
            current_indicators = await calculate_indicators(client, [asset])
            bb_upper = current_indicators.get(asset, {}).get("BB_upper")
            bb_lower = current_indicators.get(asset, {}).get("BB_lower")
            client.subscribe(asset, int(TIMEFRAME.replace('M', '')))
            await asyncio.sleep(1)
            price_data = client.candles.get_realtime_candles(asset, int(TIMEFRAME.replace('M', '')))
            current_price = extract_price(list(price_data.values())[-1] if price_data else None)
            if not current_price or bb_upper is None or bb_lower is None:
                continue
            direction = order['direction']
            open_price = order.get('open_price', current_price)
            if direction == "call" and current_price < bb_lower:
                logger.info(f"[{asset}] Trailing stop hit: Closing call at {current_price}")
                trading_state.update_loss(order['amount'])
                to_remove.append(order)
            elif direction == "put" and current_price > bb_upper:
                logger.info(f"[{asset}] Trailing stop hit: Closing put at {current_price}")
                trading_state.update_loss(order['amount'])
                to_remove.append(order)
            # Note: IQOptionAPI não tem check_win direto; usar histórico de ordens
            order_status = client.getprofile().json()['result']['orders']
            order_info = next((o for o in order_status if o['id'] == order['id']), None)
            if order_info and order_info['status'] == 'closed':
                profit = order_info['profit'] if 'profit' in order_info else 0
                if profit > 0:
                    trading_state.update_win(profit)
                else:
                    trading_state.update_loss(order['amount'])
                to_remove.append(order)
        except Exception as e:
            logger.warning(f"Error checking order {order.get('id')}: {e}")
            to_remove.append(order)
    for o in to_remove:
        trading_state.remove_order(o)

    trading_state.adjust_trade_percentage()

    for asset in assets:
        if any(o['asset'] == asset for o in trading_state.open_orders):
            logger.debug(f"[{asset}] Skipping: Already has an open order")
            continue
        if now - trading_state.last_trade_time.get(asset, 0) < TRADE_COOLDOWN:
            logger.debug(f"[{asset}] Skipping: In cooldown")
            continue

        data = indicators.get(asset, {})
        client.subscribe(asset, int(TIMEFRAME.replace('M', '')))
        await asyncio.sleep(1)
        price_data = client.candles.get_realtime_candles(asset, int(TIMEFRAME.replace('M', '')))
        price = extract_price(list(price_data.values())[-1] if price_data else None)
        if price is None:
            logger.debug(f"[{asset}] Skipped – missing price")
            continue

        direction = get_signal_for_strategy(STRATEGY, data, price)
        with open("signals_log.csv", "a", newline="") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["Timestamp", "Asset", "Price", "RSI", "SMA", "Stoch_K", "Stoch_D", "MACD", "MACD_Signal", "Strategy", "Decision", "Result"])
            w.writerow([
                datetime.now().isoformat(), asset, price,
                data.get("RSI"), data.get("SMA"),
                data.get("STOCHASTIC", {}).get("k"), data.get("STOCHASTIC", {}).get("d"),
                data.get("MACD", {}).get("macd"), data.get("MACD", {}).get("signal"),
                STRATEGY, direction or "ignored", None
            ])

        if not direction:
            logger.debug(f"[{asset}] No signal for '{STRATEGY}'")
            continue

        balance = client.getprofile().json()['result']['balance']
        amount = round((trading_state.current_trade_percentage / 100) * balance, 2)
        amount = max(1.0, min(5000.0, amount))

        if amount < 1.0 or not trading_state.check_daily_loss_limit(balance):
            logger.warning(f"[{asset}] Invalid amount or daily loss limit reached")
            continue

        try:
            check, order_id = client.buy(amount, asset, direction, TRADE_DURATION)
            if check and order_id:
                trading_state.add_order({
                    'id': order_id, 'asset': asset, 'direction': direction,
                    'amount': amount, 'open_price': price
                })
                trading_state.update_trade_time(asset, now)
            else:
                logger.warning(f"[{asset}] Trade failed: {order_id}")
        except Exception as e:
            logger.warning(f"[{asset}] Trade failed: {e}")