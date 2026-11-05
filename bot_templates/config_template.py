import logging

# ==============================================================================
# ПОДКЛЮЧЕНИЕ К БИРЖЕ
# ==============================================================================
API_KEY = {{API_KEY}}
API_SECRET = {{API_SECRET}}

# Демо-торговля Bybit (api-demo.bybit.com / stream-demo.bybit.com).
# True  — ключи созданы в кабинете «Демо-трейдинг» Bybit.
# False — обычные ключи основного аккаунта (api.bybit.com / stream.bybit.com).
# Если режим и тип ключей не совпадают, биржа отвечает 401 Unauthorized.
DEMO_TRADING = {{DEMO_TRADING}}

# ==============================================================================
# ИНСТРУМЕНТ И ТАЙМФРЕЙМ
# ==============================================================================
SYMBOL = {{SYMBOL}}
CATEGORY = {{CATEGORY}}
TIMEFRAME = {{TIMEFRAME}}

# ==============================================================================
# РАЗМЕР ПОЗИЦИИ
# ==============================================================================
RISK_PER_TRADE = {{RISK_PER_TRADE}}

# ==============================================================================
# ИНДИКАТОР BOLLINGER BANDS
# ==============================================================================
BB_LENGTH = {{BB_LENGTH}}
BB_STD_DEV = {{BB_STD_DEV}}

# ==============================================================================
# АДАПТИВНЫЙ РЕЖИМ
# ==============================================================================
ADAPTIVE_MODE = {{ADAPTIVE_MODE}}
TRAIL_PERCENT = {{TRAIL_PERCENT}}
SL_PERCENT = {{SL_PERCENT}}
TP_PERCENT = {{TP_PERCENT}}
BASE_TRAIL_PERCENT = {{BASE_TRAIL_PERCENT}}
TRAIL_GROWTH_FACTOR = {{TRAIL_GROWTH_FACTOR}}
SL_FROM_TRAIL_PERCENT = {{SL_FROM_TRAIL_PERCENT}}
TP_FROM_WIDTH_PERCENT = {{TP_FROM_WIDTH_PERCENT}}

# ==============================================================================
# КОМИССИИ
# ==============================================================================
MAKER_FEE_PERCENT = {{MAKER_FEE_PERCENT}}
TAKER_FEE_PERCENT = {{TAKER_FEE_PERCENT}}

# ==============================================================================
# ФИЛЬТРЫ ВХОДА
# ==============================================================================
RVOL_PERIOD = {{RVOL_PERIOD}}
MAX_RVOL_FOR_REVERSAL = {{MAX_RVOL_FOR_REVERSAL}}
MIN_VOLATILITY_RATIO = {{MIN_VOLATILITY_RATIO}}
MIN_CHANNEL_WIDTH_PERCENT = {{MIN_CHANNEL_WIDTH_PERCENT}}
MAX_CHANNEL_WIDTH_PERCENT = {{MAX_CHANNEL_WIDTH_PERCENT}}
TRADE_COOLDOWN_SECONDS = {{TRADE_COOLDOWN_SECONDS}}
SLOPE_LOOKBACK = {{SLOPE_LOOKBACK}}
MAX_SMA_SLOPE_PERCENT = {{MAX_SMA_SLOPE_PERCENT}}
ENABLE_SLOPE_ORDER_CANCEL = {{ENABLE_SLOPE_ORDER_CANCEL}}

# ==============================================================================
# ПРИНУДИТЕЛЬНОЕ ЗАКРЫТИЕ
# ==============================================================================
FORCE_CLOSE_AT_OPPOSITE_BAND = {{FORCE_CLOSE_AT_OPPOSITE_BAND}}
ENABLE_CHANNEL_EXPANSION_CANCEL = {{ENABLE_CHANNEL_EXPANSION_CANCEL}}
CHANNEL_EXPANSION_RATIO = {{CHANNEL_EXPANSION_RATIO}}
ENABLE_STALE_TRADE_CLOSE = {{ENABLE_STALE_TRADE_CLOSE}}
STALE_TRADE_TIMEOUT_CANDLES = {{STALE_TRADE_TIMEOUT_CANDLES}}
ENABLE_DISTANCE_CANCEL = {{ENABLE_DISTANCE_CANCEL}}
MAX_DISTANCE_FROM_TRIGGER_PERCENT = {{MAX_DISTANCE_FROM_TRIGGER_PERCENT}}

# ==============================================================================
# СИМУЛЯТОР
# ==============================================================================
SIMULATOR_MODE = {{SIMULATOR_MODE}}
SIMULATOR_BALANCE = {{SIMULATOR_BALANCE}}
SIMULATOR_COMMISSION_PERCENT = {{SIMULATOR_COMMISSION_PERCENT}}
SIMULATOR_SLIPPAGE_POINTS = {{SIMULATOR_SLIPPAGE_POINTS}}

# ==============================================================================
# СИСТЕМНЫЕ НАСТРОЙКИ (константы, не меняются через GUI)
# ==============================================================================
LOG_LEVEL = logging.INFO
SYNC_INTERVAL = 2.0
GRACE_PERIOD = 5.0
DASHBOARD_UPDATE_INTERVAL = 5.0
SIMULATOR_LOG_FILE = "simulator_history.txt"
TRADE_LOG_FILE = "trade_history.txt"
