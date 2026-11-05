import logging

# ==============================================================================
# ПОДКЛЮЧЕНИЕ К БИРЖЕ
# ==============================================================================
API_KEY = "tmrIPwIxNkfiNaSKfD"
API_SECRET = "HBT9UYrYJABSZidc1TqhaS9ra5uBdSfbxBFV"

# Демо-торговля Bybit (api-demo.bybit.com / stream-demo.bybit.com).
# True  — ключи созданы в кабинете «Демо-трейдинг» Bybit.
# False — обычные ключи основного аккаунта (api.bybit.com / stream.bybit.com).
# Если режим и тип ключей не совпадают, биржа отвечает 401 Unauthorized.
DEMO_TRADING = True

# ==============================================================================
# ИНСТРУМЕНТ И ТАЙМФРЕЙМ
# ==============================================================================
SYMBOL = "1000PEPEUSDT"
CATEGORY = "linear"
TIMEFRAME = "5"

# ==============================================================================
# РАЗМЕР ПОЗИЦИИ
# ==============================================================================
RISK_PER_TRADE = 10.0

# ==============================================================================
# ИНДИКАТОР BOLLINGER BANDS
# ==============================================================================
BB_LENGTH = 20
BB_STD_DEV = 2.2

# ==============================================================================
# АДАПТИВНЫЙ РЕЖИМ
# ==============================================================================
ADAPTIVE_MODE = True
TRAIL_PERCENT = 0.15
SL_PERCENT = 0.6
TP_PERCENT = 1.2
BASE_TRAIL_PERCENT = 0.15
TRAIL_GROWTH_FACTOR = 0.12
SL_FROM_TRAIL_PERCENT = 120.0
TP_FROM_WIDTH_PERCENT = 80.0

# ==============================================================================
# КОМИССИИ
# ==============================================================================
MAKER_FEE_PERCENT = 0.02
TAKER_FEE_PERCENT = 0.055

# ==============================================================================
# ФИЛЬТРЫ ВХОДА
# ==============================================================================
RVOL_PERIOD = 20
MAX_RVOL_FOR_REVERSAL = 500.0
MIN_VOLATILITY_RATIO = 0.5
MIN_CHANNEL_WIDTH_PERCENT = 1.0
MAX_CHANNEL_WIDTH_PERCENT = 6.0
TRADE_COOLDOWN_SECONDS = 60
SLOPE_LOOKBACK = 5
MAX_SMA_SLOPE_PERCENT = 0.2
ENABLE_SLOPE_ORDER_CANCEL = True

# ==============================================================================
# ПРИНУДИТЕЛЬНОЕ ЗАКРЫТИЕ
# ==============================================================================
FORCE_CLOSE_AT_OPPOSITE_BAND = True
ENABLE_CHANNEL_EXPANSION_CANCEL = True
CHANNEL_EXPANSION_RATIO = 2.0
ENABLE_STALE_TRADE_CLOSE = True
STALE_TRADE_TIMEOUT_CANDLES = 7
ENABLE_DISTANCE_CANCEL = True
MAX_DISTANCE_FROM_TRIGGER_PERCENT = 2.0

# ==============================================================================
# СИМУЛЯТОР
# ==============================================================================
SIMULATOR_MODE = False
SIMULATOR_BALANCE = 10000.0
SIMULATOR_COMMISSION_PERCENT = 0.055
SIMULATOR_SLIPPAGE_POINTS = 0

# ==============================================================================
# СИСТЕМНЫЕ НАСТРОЙКИ (константы, не меняются через GUI)
# ==============================================================================
LOG_LEVEL = logging.INFO
SYNC_INTERVAL = 2.0
GRACE_PERIOD = 5.0
DASHBOARD_UPDATE_INTERVAL = 5.0
SIMULATOR_LOG_FILE = "simulator_history.txt"
TRADE_LOG_FILE = "trade_history.txt"
