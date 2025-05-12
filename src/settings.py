from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
IS_DEMO = os.getenv("IS_DEMO", "true").lower() in ("1", "true", "yes")

TIMEFRAME = os.getenv("TIMEFRAME", "1M").upper()
MIN_PAYOUT = float(os.getenv("MIN_PAYOUT", "80"))
ASSETS = os.getenv("ASSETS", "").split(",") if os.getenv("ASSETS") else []
SORT_BY = os.getenv("SORT_BY", "payout").lower()
SORT_ORDER = os.getenv("SORT_ORDER", "desc").lower()
INDICATOR_TIMEOUT = float(os.getenv("INDICATOR_TIMEOUT", "60.0"))

RSI_INDICATOR = os.getenv("RSI_INDICATOR", "true").lower() in ("true", "yes", "1")
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_MIN = float(os.getenv("RSI_MIN", "-inf"))
RSI_MAX = float(os.getenv("RSI_MAX", "inf"))
RSI_BUY_THRESHOLD = float(os.getenv("RSI_BUY_THRESHOLD", "35"))
RSI_SELL_THRESHOLD = float(os.getenv("RSI_SELL_THRESHOLD", "65"))

SMA_INDICATOR = os.getenv("SMA_INDICATOR", "true").lower() in ("true", "yes", "1")
SMA_PERIOD = int(os.getenv("SMA_PERIOD", "20"))
SMA_MIN = float(os.getenv("SMA_MIN", "-inf"))
SMA_MAX = float(os.getenv("SMA_MAX", "inf"))

EMA_INDICATOR = os.getenv("EMA_INDICATOR", "false").lower() in ("true", "yes", "1")
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "20"))
EMA_MIN = float(os.getenv("EMA_MIN", "-inf"))
EMA_MAX = float(os.getenv("EMA_MAX", "inf"))

STOCHASTIC_INDICATOR = os.getenv("STOCHASTIC_INDICATOR", "true").lower() in ("true", "yes", "1")
STOCHASTIC_K_PERIOD = int(os.getenv("STOCHASTIC_K_PERIOD", "14"))
STOCHASTIC_D_PERIOD = int(os.getenv("STOCHASTIC_D_PERIOD", "3"))
STOCHASTIC_BUY_THRESHOLD = float(os.getenv("STOCHASTIC_BUY_THRESHOLD", "20"))
STOCHASTIC_SELL_THRESHOLD = float(os.getenv("STOCHASTIC_SELL_THRESHOLD", "80"))

MACD_INDICATOR = os.getenv("MACD_INDICATOR", "true").lower() in ("true", "yes", "1")
MACD_FAST_PERIOD = int(os.getenv("MACD_FAST_PERIOD", "12"))
MACD_SLOW_PERIOD = int(os.getenv("MACD_SLOW_PERIOD", "26"))
MACD_SIGNAL_PERIOD = int(os.getenv("MACD_SIGNAL_PERIOD", "9"))

TRADE_ENABLED = os.getenv("TRADE_ENABLED", "false").lower() in ("true", "yes", "1")
TRADE_PERCENTAGE = float(os.getenv("TRADE_PERCENTAGE", "5"))
TRADE_PERCENTAGE_MIN = float(os.getenv("TRADE_PERCENTAGE_MIN", "2"))
TRADE_PERCENTAGE_MAX = float(os.getenv("TRADE_PERCENTAGE_MAX", "5"))
TRADE_DURATION = int(os.getenv("TRADE_DURATION", "120"))
TRADE_COOLDOWN = int(os.getenv("TRADE_COOLDOWN", "300"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "10"))
CONSECUTIVE_LOSSES_THRESHOLD = int(os.getenv("CONSECUTIVE_LOSSES_THRESHOLD", "2"))
CONSECUTIVE_WINS_THRESHOLD = int(os.getenv("CONSECUTIVE_WINS_THRESHOLD", "2"))

STRATEGY = os.getenv("STRATEGY", "trend").lower()