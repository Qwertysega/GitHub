import time
import logging
import json
import os
import config
import filters

# ==============================================================================
# 1. ВЫБОР ДВИЖКА + АВТООПРЕДЕЛЕНИЕ TICK_SIZE
# ==============================================================================
if getattr(config, 'SIMULATOR_MODE', False):
    try:
        from simulator import SimulatorClient
        exchange = SimulatorClient()
        logger_main = logging.getLogger(__name__)
        logger_main.info(f"🎮 ЗАПУЩЕН РЕЖИМ СИМУЛЯТОРА для {config.SYMBOL}")
    except ImportError:
        print("❌ Ошибка: не удалось найти simulator.py.")
        exit(1)
else:
    try:
        from exchange import BybitClient
        exchange = BybitClient()
        logger_main = logging.getLogger(__name__)
        logger_main.info(f"🌐 ЗАПУЩЕН РЕЖИМ БИРЖИ (Bybit API) для {config.SYMBOL}")
    except ImportError:
        print("❌ Ошибка: не удалось найти exchange.py.")
        exit(1)

# Автоматическое определение TICK_SIZE для текущего символа
TICK_SIZE = 0.00001
try:
    _inst_info = exchange.rest.get_instruments_info(
        category=getattr(config, 'CATEGORY', 'linear'),
        symbol=config.SYMBOL
    )
    if _inst_info.get('retCode') == 0 and _inst_info['result']['list']:
        TICK_SIZE = float(_inst_info['result']['list'][0]['priceFilter']['tickSize'])
    else:
        logger_main.warning(f"⚠️ Не удалось получить tickSize, fallback={TICK_SIZE}")
except Exception as _e:
    logger_main.warning(f"⚠️ Ошибка получения tickSize: {_e}, fallback={TICK_SIZE}")

logger_main.info(f"📏 TICK_SIZE для {config.SYMBOL}: {TICK_SIZE}")

# ==============================================================================
# 2. НАСТРОЙКА ЛОГИРОВАНИЯ
# ==============================================================================
_LOG_LEVEL = getattr(config, 'LOG_LEVEL', logging.INFO)
logging.basicConfig(level=_LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')

trade_logger = logging.getLogger("TradeHistory")
trade_logger.setLevel(logging.INFO)
trade_logger.propagate = False

_SIM_LOG = getattr(config, 'SIMULATOR_LOG_FILE', 'simulator_history.txt')
_TRADE_LOG = getattr(config, 'TRADE_LOG_FILE', 'trade_history.txt')
active_log_file = _SIM_LOG if getattr(config, 'SIMULATOR_MODE', False) else _TRADE_LOG

file_handler = logging.FileHandler(active_log_file, encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
trade_logger.addHandler(file_handler)

sys_handler = logging.FileHandler("startup_error.log", encoding="utf-8")
sys_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
sys_handler.setLevel(logging.DEBUG)
logger_main.addHandler(sys_handler)

# ==============================================================================
# 3. ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ==============================================================================
state = {
    "current_price": 0.0,
    "upper_bb": 0.0,
    "lower_bb": 0.0,
    "active_order_id": None,
    "order_side": None,
    "current_trigger_price": 0.0,
    "initial_balance": 0.0,
    "position_side": None,
    "is_in_position": False,
    "order_creation_time": 0.0,
    "closes": [],
    "last_trade_direction": None,
    "last_trade_candle_time": 0,
    "closed_volumes": [],
    "current_candle_volume": 0.0,
    "closed_ranges": [],
    "current_candle_range": 0.0,
    "last_candle_time": 0,
    "stats": {"total_trades": 0, "wins": 0, "losses": 0, "session_pnl": 0.0},
    "last_trade_close_time": 0.0,
    "is_placing_order": False,
    "channel_width_at_order_open": 0.0,
    "candles_since_open": [],
    "entry_price": 0.0,
    "is_closing": False,
    "lot_size": 0,
    "active_sl": 0.0,
    "active_tp": 0.0,
    "is_force_closing": False,
    "current_sma_slope": 0.0,
    "adaptive_trail_pct": 0.0,
    "adaptive_sl_pct": 0.0,
    "adaptive_tp_pct": 0.0,
    "last_ws_exit_price": 0.0,
    "last_ws_exit_time": 0.0,
    "last_seen_pos_size": 0.0,
}

last_trail_log_time = 0
last_sync_time = 0
last_dashboard_time = 0

# Флаг graceful shutdown: signal handler выставляет его, WS-потоки проверяют
# и выходят из циклов переподключения (иначе terminate() убивает процесс,
# а сокет-треды продолжают сыпать ошибками в startup_error.log).
shutdown_requested = False


def _log_throttle(key: str, message: str, level: int = logging.INFO, interval: float = 60.0) -> None:
    """
    Логирует сообщение не чаще одного раза в `interval` секунд на ключ.
    Нужен потому, что Bybit ticker stream шлёт апдейты несколько раз в секунду
    и фильтры-«пропуски» без троттлинга забивают системный лог.
    """
    now = time.time()
    last = _log_throttle_state.get(key, 0.0)
    if now - last < interval:
        return
    _log_throttle_state[key] = now
    logger_main.log(level, message)


_log_throttle_state: dict = {}


# ==============================================================================
# 3.1 РАСЧЁТ АДАПТИВНЫХ ПАРАМЕТРОВ
# ==============================================================================
def calculate_adaptive_params(channel_width_pct):
    if not getattr(config, 'ADAPTIVE_MODE', False):
        return config.TRAIL_PERCENT, config.SL_PERCENT, config.TP_PERCENT
    min_width = config.MIN_CHANNEL_WIDTH_PERCENT
    base_trail = config.BASE_TRAIL_PERCENT
    growth = config.TRAIL_GROWTH_FACTOR
    sl_ratio = config.SL_FROM_TRAIL_PERCENT
    tp_ratio = config.TP_FROM_WIDTH_PERCENT
    trail_pct = base_trail + max(0.0, channel_width_pct - min_width) * growth
    sl_pct = trail_pct * sl_ratio / 100.0
    tp_pct = channel_width_pct * tp_ratio / 100.0
    return trail_pct, sl_pct, tp_pct


# ==============================================================================
# 4. ДАШБОРД КОНСОЛИ
# ==============================================================================
def get_global_stats():
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0
    try:
        with open(active_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if 'ЗАКРЫТИЕ' in line or 'CLOSE' in line:
                    total_trades += 1
                    if 'PnL:' in line:
                        try:
                            pnl_part = line.split('PnL:')[1].split('|')[0].strip()
                            pnl_value = float(pnl_part.replace('+', '').replace('USDT', '').strip())
                            total_pnl += pnl_value
                            if pnl_value > 0:
                                total_wins += 1
                            else:
                                total_losses += 1
                        except Exception:
                            pass
    except FileNotFoundError:
        pass
    except Exception as e:
        logger_main.error(f"Ошибка чтения статистики: {e}")
    return total_trades, total_wins, total_losses, total_pnl


def print_dashboard():
    try:
        balance = exchange.get_balance()
        pnl = state["stats"]["session_pnl"]
        total_return = (pnl / state["initial_balance"] * 100) if state["initial_balance"] > 0 else 0.0
        price = state["current_price"]
        lower, upper = state["lower_bb"], state["upper_bb"]
        sma = (lower + upper) / 2.0 if upper > 0 else 0.0
        channel_width_pct = ((upper - lower) / price * 100) if price > 0 else 0.0
        curr_vol = state["current_candle_range"]
        avg_vol = sum(state["closed_ranges"]) / len(state["closed_ranges"]) if state["closed_ranges"] else curr_vol
        req_vol = avg_vol * config.MIN_VOLATILITY_RATIO
        curr_rvol = filters.calculate_rvol(state["current_candle_volume"], state["closed_volumes"])
        max_rvol = config.MAX_RVOL_FOR_REVERSAL
        spread = exchange.get_spread()
        spread_pts = spread / TICK_SIZE if TICK_SIZE > 0 else 0.0
        ws_status_raw = getattr(exchange, 'ws_status', 'Unknown')
        ws_status_str = f"SIM: {ws_status_raw}" if config.SIMULATOR_MODE else f"Pub:{ws_status_raw.split(' ')[0]} Prv:{ws_status_raw.split(' ')[0]}"

        if state["is_in_position"]:
            status = f"IN POSITION ({state['position_side']})"
            order_info = "SL/TP Active"
            dist_info = "HOLDING"
        elif state["active_order_id"]:
            status = f"PENDING ORDER ({state['order_side']})"
            order_info = f"Trig: {state['current_trigger_price']:.8f}"
            dist_pct = abs((price - state['current_trigger_price']) / price * 100) if price > 0 else 0
            dist_info = f"Dist: {dist_pct:.2f}%"
        else:
            status = "MONITORING"
            order_info = "No active orders"
            dist_info = "Waiting for signal"

        stats = state["stats"]
        win_rate = (stats["wins"] / stats["total_trades"] * 100) if stats["total_trades"] > 0 else 0.0
        mode_tag = "[SIMULATOR]" if config.SIMULATOR_MODE else "[LIVE API]"
        adaptive_tag = "ADAPTIVE" if getattr(config, 'ADAPTIVE_MODE', False) else "FIXED"
        global_trades, global_wins, global_losses, global_pnl = get_global_stats()
        global_win_rate = (global_wins / global_trades * 100) if global_trades > 0 else 0.0
        stale_count = len(state.get("candles_since_open", []))
        stale_limit = config.STALE_TRADE_TIMEOUT_CANDLES if getattr(config, 'ENABLE_STALE_TRADE_CLOSE', False) else 0
        stale_info = f"{stale_count}/{stale_limit}" if stale_limit > 0 and state["is_in_position"] else "OFF"

        def row(l, r):
            return f"║ {l:<29} │ {r:<29} ║"

        b_top = "╔" + "═" * 63 + "╗"
        b_mid = "╠" + "═" * 63 + "╣"
        b_bot = "╚" + "═" * 63 + "╝"
        timeframe_str = f"M{config.TIMEFRAME}"
        header = f"BOT v34.0 - {config.SYMBOL} [{timeframe_str}] {mode_tag} [{adaptive_tag}]"

        a_trail = state.get("adaptive_trail_pct", 0.0)
        a_sl = state.get("adaptive_sl_pct", 0.0)
        a_tp = state.get("adaptive_tp_pct", 0.0)

        lines = [
            b_top,
            f"║{header:^63}║",
            b_mid,
            row(f"Initial Balance: {state['initial_balance']:.2f} USDT", f"Current: {balance:.2f} USDT"),
            row(f"Total Return: {total_return:+.2f}%", f"Total PnL: {pnl:+.2f} USDT"),
            b_mid,
            row(f"Status: {status}", f"Trades: {stats['total_trades']} (W:{stats['wins']}/L:{stats['losses']})"),
            row(f"Win Rate: {win_rate:.1f}%", f"WS Conn: {ws_status_str}"),
            b_mid,
            row(f"Price: {price:.8f}", f"SMA: {sma:.8f}"),
            row(f"Spread: {spread:.8f} ({spread_pts:.1f} pts)", f"Channel Width: {channel_width_pct:.2f}%"),
            row(f"Cur. Volatility: {curr_vol:.8f}", f"Min Required: {req_vol:.8f}"),
            row(f"Volume (RVOL): {curr_rvol:.2f}x", f"Max Allowed: {max_rvol:.2f}x"),
            row(f"SMA Slope: {state['current_sma_slope']:.3f}%", f"Max Slope: {config.MAX_SMA_SLOPE_PERCENT}%"),
            b_mid,
            row(f"Order Info: {order_info}", dist_info),
            row(f"Stale Counter: {stale_info}", f"Cooldown: {config.TRADE_COOLDOWN_SECONDS}s"),
            b_mid,
            f"║{'ACTIVE PARAMS':^63}║",
            b_mid,
            row(f"Trail: {a_trail:.3f}%", f"SL: {a_sl:.3f}% / TP: {a_tp:.3f}%"),
            row(f"BB: {config.BB_LENGTH}/{config.BB_STD_DEV}", f"RVOL Max: {config.MAX_RVOL_FOR_REVERSAL}"),
            row(f"Channel: {config.MIN_CHANNEL_WIDTH_PERCENT}-{config.MAX_CHANNEL_WIDTH_PERCENT}%", f"Stale Limit: {config.STALE_TRADE_TIMEOUT_CANDLES}"),
            row(f"Risk/Trade: {config.RISK_PER_TRADE}%", f"Lot: {state.get('lot_size', 'N/A')}"),
            b_mid,
            f"║{'GLOBAL STATS (from file)':^63}║",
            b_mid,
            row(f"Total Trades: {global_trades}", f"Win Rate: {global_win_rate:.1f}%"),
            row(f"Total PnL: {global_pnl:+.2f} USDT", f"W:{global_wins} / L:{global_losses}"),
            b_bot
        ]
        os.system('cls' if os.name == 'nt' else 'clear')
        output = "\n".join(line.rstrip() for line in lines)
        try:
            print(output)
        except UnicodeEncodeError:
            safe_output = output.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(safe_output)
    except Exception as e:
        logger_main.error(f"Ошибка дашборда: {e}")


# ==============================================================================
# 5. ЛОГИКА ИНДИКАТОРОВ И СОСТОЯНИЯ
# ==============================================================================
def calculate_bb():
    if len(state["closes"]) < config.BB_LENGTH:
        return
    closes = [c['close'] for c in state["closes"][-config.BB_LENGTH:]]
    sma = sum(closes) / config.BB_LENGTH
    std_dev = (sum((x - sma) ** 2 for x in closes) / config.BB_LENGTH) ** 0.5
    state["upper_bb"] = sma + (std_dev * config.BB_STD_DEV)
    state["lower_bb"] = sma - (std_dev * config.BB_STD_DEV)


def calculate_sma_slope():
    lookback = getattr(config, 'SLOPE_LOOKBACK', 5)
    required_len = config.BB_LENGTH + lookback
    if len(state["closes"]) < required_len:
        state["current_sma_slope"] = 0.0
        return 0.0
    current_closes = [c['close'] for c in state["closes"][-config.BB_LENGTH:]]
    sma_current = sum(current_closes) / config.BB_LENGTH
    prev_end = -lookback
    prev_start = prev_end - config.BB_LENGTH
    prev_closes = [c['close'] for c in state["closes"][prev_start:prev_end]]
    sma_prev = sum(prev_closes) / config.BB_LENGTH
    slope_pct = abs(sma_current - sma_prev) / sma_current * 100 if sma_current > 0 else 0.0
    state["current_sma_slope"] = slope_pct
    return slope_pct


def calculate_lot_size(current_price):
    try:
        balance = exchange.get_balance()
        if balance <= 0:
            logger_main.warning("⚠️ Баланс 0, использую fallback лот 10000")
            return 10000
        # В адаптивном режиме используем динамический SL из стейта
        sl_pct = state.get("adaptive_sl_pct", 0.0)
        if sl_pct <= 0:
            sl_pct = getattr(config, 'SL_PERCENT', 0.6)
        risk_usdt = balance * (config.RISK_PER_TRADE / 100.0)
        lot_size = risk_usdt / (current_price * (sl_pct / 100.0))
        lot_size = int(round(lot_size))
        max_position_value = balance * 0.5
        max_lot_size = int(max_position_value / current_price)
        if lot_size > max_lot_size:
            logger_main.warning(f"⚠️ Расчётный лот {lot_size} превышает лимит {max_lot_size}, использую максимум")
            lot_size = max_lot_size
        return lot_size
    except Exception as e:
        logger_main.error(f"❌ Ошибка расчёта лота: {e}")
        return 10000


def _live_close_fallback(side, exit_price, lot_size):
    """Fallback-расчёт для LIVE: реальные fills по входу и выходу (цена, количество, комиссия)."""
    try:
        execs = exchange.get_recent_executions(limit=30)
    except Exception as e:
        logger_main.error(f"❌ Не удалось получить исполнения: {e}")
        return None

    entry_execs, exit_execs = [], []
    close_side = "Sell" if str(side).upper() == "BUY" else "Buy"
    for e in execs:
        if str(e["side"]).upper() == str(side).upper():
            entry_execs.append(e)
        elif str(e["side"]).upper() == close_side.upper():
            exit_execs.append(e)

    # Последние исполнения = вход и выход этой сделки (бот торгует одной позицией)
    take_qty = float(lot_size) if lot_size > 0 else 0.0
    if take_qty <= 0:
        take_qty = sum(e["qty"] for e in exit_execs) or 1

    def _take_last(ex_list, qty):
        picked, acc = [], 0.0
        for e in reversed(ex_list):
            picked.append(e)
            acc += e["qty"]
            if acc >= qty:
                break
        return picked

    entry_picked = _take_last(entry_execs, take_qty)
    exit_picked = _take_last(exit_execs, take_qty)
    if not exit_picked or not entry_picked:
        return None

    entry_notional = sum(e["price"] * e["qty"] for e in entry_picked)
    exit_notional = sum(e["price"] * e["qty"] for e in exit_picked)
    entry_qty = sum(e["qty"] for e in entry_picked)
    exit_qty = sum(e["qty"] for e in exit_picked)
    real_entry = entry_notional / entry_qty if entry_qty > 0 else state.get("entry_price", 0.0)
    real_exit = exit_notional / exit_qty if exit_qty > 0 else exit_price

    # execFee у Bybit уже со знаком минус (возврат мейкер-комиссии учитывается биржей)
    fees_abs = abs(sum(e["fee"] for e in entry_picked)) + abs(sum(e["fee"] for e in exit_picked))
    if str(side).upper() == "BUY":
        gross = exit_notional - entry_notional * (exit_qty / entry_qty if entry_qty > 0 else 1)
    else:
        gross = entry_notional * (exit_qty / entry_qty if entry_qty > 0 else 1) - exit_notional
    pnl_net = gross - fees_abs
    return real_entry, real_exit, exit_qty, pnl_net


def log_position_close(side, exit_price, reason):
    if state.get("is_closing", False):
        return
    state["is_closing"] = True
    try:
        entry_price = state.get("entry_price", 0.0)
        lot_size = state.get("lot_size", 0)
        is_live = not getattr(config, 'SIMULATOR_MODE', False)
        commission = None
        pnl_net = None

        # === LIVE: берём РЕАЛЬНЫЕ данные биржи, а не оценку бота ===
        if is_live and hasattr(exchange, 'get_position_data'):
            pos_data = exchange.get_position_data()
            if pos_data["size"] < 0:
                logger_main.warning("⚠️ Не удалось получить позицию с биржи, PnL может быть оценочным")
            realized = pos_data["realized_pnl"]
            if realized != 0.0:
                # Позиция закрыта — realizedPnl содержит итоговый результат по сделке (уже за вычетом комиссий)
                pnl_net = realized
                entry_price = pos_data["avg_price"] if pos_data["avg_price"] > 0 else entry_price
                lot_size = lot_size if lot_size > 0 else pos_data["size"]
            else:
                fallback = _live_close_fallback(side, exit_price, lot_size)
                if fallback:
                    entry_price, exit_price, lot_size, pnl_net = fallback
                else:
                    logger_main.warning("⚠️ realizedPnl пуст и fills недоступны — использую оценку по ценам бота, сверьтесь с биржей")

        if commission is None and pnl_net is None:
            commission_rate = config.TAKER_FEE_PERCENT / 100.0
            trade_volume_entry = entry_price * lot_size
            trade_volume_exit = exit_price * lot_size
            commission = (trade_volume_entry + trade_volume_exit) * commission_rate
            if str(side).upper() == "BUY":
                pnl = (exit_price - entry_price) * lot_size
            else:
                pnl = (entry_price - exit_price) * lot_size
            pnl_net = pnl - commission

        state["stats"]["total_trades"] += 1
        state["stats"]["session_pnl"] += pnl_net
        if pnl_net > 0:
            state["stats"]["wins"] += 1
        else:
            state["stats"]["losses"] += 1

        price = state["current_price"]
        upper = state["upper_bb"]
        lower = state["lower_bb"]
        channel_width_pct = ((upper - lower) / price * 100) if price > 0 else 0.0
        spread = exchange.get_spread()
        current_balance = exchange.get_balance()

        comm_str = " | Комиссия: биржа" if is_live and commission is None else f" | Комиссия: {commission:.4f} USDT"
        trade_logger.info(
            f"🔴 ЗАКРЫТИЕ {str(side).upper()} | Причина: {reason} |  "
            f"Цена закрытия: {exit_price:.8f} |  "
            f"Цена входа: {entry_price:.8f} | Лот: {lot_size} |  "
            f"PnL: {pnl_net:+.4f} USDT{comm_str} | Баланс: {current_balance:.2f} |  "
            f"Спред: {spread:.8f} | Ширина канала: {channel_width_pct:.2f}%"
        )
        logger_main.info(f"✅ Позиция закрыта по {reason} @ {exit_price:.8f}! PnL: {pnl_net:+.4f} USDT")

        state["last_trade_close_time"] = time.time()
        state.update({
            "is_in_position": False, "position_side": None,
            "active_order_id": None, "order_side": None,
            "current_trigger_price": 0.0, "order_creation_time": 0.0,
            "channel_width_at_order_open": 0.0, "candles_since_open": [],
            "entry_price": 0.0, "lot_size": 0,
            "active_sl": 0.0, "active_tp": 0.0,
            "is_force_closing": False,
            "adaptive_trail_pct": 0.0, "adaptive_sl_pct": 0.0, "adaptive_tp_pct": 0.0,
        })
    finally:
        state["is_closing"] = False


def sync_state():
    global last_sync_time
    if time.time() - last_sync_time < getattr(config, 'SYNC_INTERVAL', 2.0):
        return
    last_sync_time = time.time()

    if state.get("is_closing", False):
        return

    pos_size, pos_side = exchange.get_position()

    # Запоминаем размер позиции, чтобы после закрытия сопоставить объём филла
    if pos_size > 0:
        state["last_seen_pos_size"] = pos_size
    pos_size_last = state.get("last_seen_pos_size", 0.0)

    # Позиция исчезла
    if state["is_in_position"] and pos_size == 0:
        exit_price = state["current_price"]
        side = state["position_side"]

        # 1) Точная цена выхода из private WS (order stream, срабатывание SL/TP) — без задержек REST
        ws_exit = state.get("last_ws_exit_price", 0.0)
        ws_age = time.time() - state.get("last_ws_exit_time", 0.0)
        if ws_exit > 0 and ws_age <= 60.0:
            exit_price = ws_exit
        if ws_exit > 0:
            state["last_ws_exit_price"] = 0.0
        # 2) LIVE fallback: уточняем по последнему исполнению на бирже
        elif not getattr(config, 'SIMULATOR_MODE', False) and hasattr(exchange, 'get_recent_executions'):
            try:
                close_side = "Sell" if str(side).upper() == "BUY" else "Buy"
                execs = [e for e in exchange.get_recent_executions(limit=10)
                         if str(e["side"]).upper() == close_side.upper()]
                if execs:
                    last_qty = execs[-1]["qty"]
                    same_ts = [e for e in execs if e["created_ms"] == execs[-1]["created_ms"]]
                    total_qty = sum(e["qty"] for e in same_ts)
                    vwap = (sum(e["price"] * e["qty"] for e in same_ts) / total_qty) if total_qty > 0 else execs[-1]["price"]
                    # Берём исполнение, сопоставимое по объёму с позицией — иначе это чужой/частичный филл
                    if last_qty >= pos_size_last * 0.5 or abs(vwap - exit_price) / max(exit_price, 1e-12) < 0.01:
                        exit_price = vwap
            except Exception as e:
                logger_main.warning(f"⚠️ Не удалось уточнить цену закрытия по fills: {e}")

        if state.get("is_force_closing", False):
            reason = "Bot Force Close"
            log_position_close(side, exit_price, reason)
            state["is_force_closing"] = False
            return

        active_sl = state.get("active_sl", 0.0)
        active_tp = state.get("active_tp", 0.0)
        reason = "Unknown"
        tolerance = 0.001

        if side == "Buy":
            if active_tp > 0 and exit_price >= active_tp * (1 - tolerance):
                reason = "Take Profit"
            elif active_sl > 0 and exit_price <= active_sl * (1 + tolerance):
                reason = "Stop Loss"
            else:
                reason = "External Close / Liquidation"
        else:
            if active_tp > 0 and exit_price <= active_tp * (1 + tolerance):
                reason = "Take Profit"
            elif active_sl > 0 and exit_price >= active_sl * (1 - tolerance):
                reason = "Stop Loss"
            else:
                reason = "External Close / Liquidation"

        log_position_close(side, exit_price, reason)
        return

    # === ПОЗИЦИЯ ПОЯВИЛАСЬ ===
    if pos_size > 0 and not state["is_in_position"]:
        # LIVE: берём РЕАЛЬНУЮ среднюю цену входа и фактический размер с биржи.
        # state["current_price"] (последний тикер) может заметно отличаться от цены
        # исполнения стоп-ордера — это главный источник расхождений PnL с биржей.
        exec_price = state["current_price"]
        if not getattr(config, 'SIMULATOR_MODE', False) and hasattr(exchange, 'get_position_data'):
            try:
                pd = exchange.get_position_data()
                if pd["size"] >= 0 and pd["avg_price"] > 0:
                    exec_price = pd["avg_price"]
                    pos_size = pd["size"] if pd["size"] > 0 else pos_size
                    if pd["side"]:
                        pos_side = pd["side"]
            except Exception as e:
                logger_main.warning(f"⚠️ Не удалось получить avgPrice позиции: {e}")
        state["entry_price"] = exec_price
        state["lot_size"] = pos_size
        # Сторона входа: приоритет у ордера бота, иначе — фактическая сторона позиции с биржи
        entry_side = state.get("order_side") or pos_side or ("Buy" if str(state.get("position_side", "")).upper() == "BUY" else "Sell")

        # Пишем ⚡ ИСПОЛНЕНИЕ ТОЛЬКО в LIVE режиме
        # В SIM режиме симулятор УЖЕ записал это в _process_market_tick
        if not getattr(config, 'SIMULATOR_MODE', False):
            trade_logger.info(
                f"⚡ ИСПОЛНЕНИЕ {str(entry_side).upper()} | Статус: Triggered (sync) |  "
                f"Факт. цена: {exec_price:.8f} | Триггер: {state['current_trigger_price']:.8f} |  "
                f"SL: {state['active_sl']:.8f} | TP: {state['active_tp']:.8f} |  "
                f"SMA Slope: {state['current_sma_slope']:.3f}%"
            )

        logger_main.info(f"✅ Позиция {entry_side} открыта (sync)! Размер: {pos_size}, Вход: {exec_price:.8f}")
        state.update({"is_in_position": True, "position_side": entry_side, "active_order_id": None})
        return

    # Force Close на противоположной границе
    if state["is_in_position"] and getattr(config, 'FORCE_CLOSE_AT_OPPOSITE_BAND', False):
        price = state["current_price"]
        upper = state["upper_bb"]
        lower = state["lower_bb"]
        if upper > 0.0 and lower > 0.0:
            last_candle_high = state["closes"][-1]['high'] if state["closes"] else price
            last_candle_low = state["closes"][-1]['low'] if state["closes"] else price
            force_close = False
            if state["position_side"] == "Buy" and (price >= upper or last_candle_high >= upper):
                force_close = True
                logger_main.info(f"⚡ Force Close: цена {price:.8f} (high: {last_candle_high:.8f}) >= upper {upper:.8f}")
            elif state["position_side"] == "Sell" and (price <= lower or last_candle_low <= lower):
                force_close = True
                logger_main.info(f"⚡ Force Close: цена {price:.8f} (low: {last_candle_low:.8f}) <= lower {lower:.8f}")
            if force_close:
                state["is_force_closing"] = True
                exchange.close_position(state["position_side"])
                return

    # Отмена ордера при расширении канала
    if state["active_order_id"] and getattr(config, 'ENABLE_CHANNEL_EXPANSION_CANCEL', False):
        upper = state["upper_bb"]
        lower = state["lower_bb"]
        width_at_open = state.get("channel_width_at_order_open", 0.0)
        if upper > 0.0 and lower > 0.0 and width_at_open > 0.0:
            current_width = upper - lower
            expansion_ratio = current_width / width_at_open
            if expansion_ratio >= config.CHANNEL_EXPANSION_RATIO:
                logger_main.info(
                    f"⚠️ Отмена ордера: канал расширился в {expansion_ratio:.2f}x "
                    f"(было {width_at_open:.8f}, стало {current_width:.8f})"
                )
                exchange.cancel_order(state["active_order_id"])
                state.update({
                    "active_order_id": None, "order_side": None,
                    "current_trigger_price": 0.0, "order_creation_time": 0.0,
                    "channel_width_at_order_open": 0.0
                })

    # Отмена ордера при удалении от триггера
    if state["active_order_id"] and getattr(config, 'ENABLE_DISTANCE_CANCEL', False):
        price = state["current_price"]
        trigger = state["current_trigger_price"]
        if price > 0 and trigger > 0:
            distance_pct = abs((price - trigger) / price * 100)
            if distance_pct > config.MAX_DISTANCE_FROM_TRIGGER_PERCENT:
                logger_main.info(
                    f"⚠️ Отмена ордера: цена ушла слишком далеко от триггера "
                    f"(расстояние: {distance_pct:.2f}%, лимит: {config.MAX_DISTANCE_FROM_TRIGGER_PERCENT}%)"
                )
                exchange.cancel_order(state["active_order_id"])
                state.update({
                    "active_order_id": None, "order_side": None,
                    "current_trigger_price": 0.0, "order_creation_time": 0.0,
                    "channel_width_at_order_open": 0.0
                })
                return

    # Проверка существования ордера
    if state["active_order_id"]:
        grace = getattr(config, 'GRACE_PERIOD', 5.0)
        if time.time() - state["order_creation_time"] < grace:
            return
        if not exchange.check_order_exists(state["active_order_id"]):
            trade_logger.info(f"⚪ ОТМЕНА ордера {state['order_side'].upper()} | Причина: Исчез без исполнения")
            logger_main.info("🏁 Ордер исчез и не стал позицией. Бот свободен.")
            state.update({
                "active_order_id": None, "order_side": None,
                "current_trigger_price": 0.0, "order_creation_time": 0.0,
                "channel_width_at_order_open": 0.0
            })


# ==============================================================================
# 6. ТОРГОВАЯ ЛОГИКА
# ==============================================================================
def place_order_logic(side, trigger_price, trail_pct, sl_pct, tp_pct):
    if state["active_order_id"] or state["is_in_position"]:
        return
    if state.get("is_placing_order", False):
        logger_main.warning("⚠️ Пропуск сигнала: уже идет процесс размещения ордера.")
        return

    pos_size, pos_side = exchange.get_position()
    if pos_size > 0:
        logger_main.warning(f"⚠️ Пропуск сигнала: на бирже уже открыта позиция {pos_side} ({pos_size})")
        return

    state["is_placing_order"] = True
    try:
        lot_size = calculate_lot_size(trigger_price)
        sl = trigger_price * (1 + sl_pct / 100) if side == "Sell" else trigger_price * (1 - sl_pct / 100)
        tp = trigger_price * (1 - tp_pct / 100) if side == "Sell" else trigger_price * (1 + tp_pct / 100)

        rvol = filters.calculate_rvol(state["current_candle_volume"], state["closed_volumes"])
        curr_vol = state["current_candle_range"]
        price = state["current_price"]
        upper = state["upper_bb"]
        lower = state["lower_bb"]
        channel_width_pct = ((upper - lower) / price * 100) if price > 0 else 0.0
        channel_width_abs = upper - lower
        spread = exchange.get_spread()
        adaptive_tag = "ADAPTIVE" if getattr(config, 'ADAPTIVE_MODE', False) else "FIXED"

        logger_main.info(
            f"📝 {side}-stop [{adaptive_tag}] | Триггер: {trigger_price:.8f}, "
            f"SL: {sl:.8f} ({sl_pct:.3f}%), TP: {tp:.8f} ({tp_pct:.3f}%), "
            f"Trail: {trail_pct:.3f}%, Лот: {lot_size}"
        )
        trade_logger.info(
            f"🟢 ОТКРЫТИЕ {side.upper()} | Цена: {price:.8f} | Триггер: {trigger_price:.8f} |  "
            f"SL: {sl:.8f} ({sl_pct:.3f}%) | TP: {tp:.8f} ({tp_pct:.3f}%) | Лот: {lot_size} |  "
            f"Спред: {spread:.8f} | Ширина канала: {channel_width_pct:.2f}% |  "
            f"Условия: RVOL={rvol:.2f}, Волатильность={curr_vol:.8f}, "
            f"SMA Slope={state['current_sma_slope']:.3f}%, Trail={trail_pct:.3f}%"
        )

        order_id = exchange.place_order(side, trigger_price, sl, tp, lot_size, sma_slope=state['current_sma_slope'])
        if order_id:
            state.update({
                "active_order_id": order_id,
                "order_side": side,
                "current_trigger_price": trigger_price,
                "order_creation_time": time.time(),
                "initial_balance": exchange.get_balance(),
                "last_trade_direction": side,
                "last_trade_candle_time": state["last_candle_time"],
                "channel_width_at_order_open": channel_width_abs,
                "entry_price": price,
                "lot_size": lot_size,
                "active_sl": sl,
                "active_tp": tp,
                "adaptive_trail_pct": trail_pct,
                "adaptive_sl_pct": sl_pct,
                "adaptive_tp_pct": tp_pct,
            })
            logger_main.info(
                f"✅ Ордер создан! ID: {order_id} | Лот: {lot_size} | "
                f"Trail: {trail_pct:.3f}% | SL: {sl_pct:.3f}% | TP: {tp_pct:.3f}%"
            )
        else:
            logger_main.error("❌ Биржа отклонила создание ордера.")
    except Exception as e:
        logger_main.error(f"❌ Исключение при размещении ордера: {e}")
    finally:
        state["is_placing_order"] = False


def trail_order_logic():
    global last_trail_log_time
    if not state["active_order_id"]:
        return

    if getattr(config, 'ENABLE_SLOPE_ORDER_CANCEL', False):
        slope_pct = calculate_sma_slope()
        max_slope = getattr(config, 'MAX_SMA_SLOPE_PERCENT', 0.15)
        if slope_pct > max_slope:
            logger_main.info(
                f"⚠️ Отмена ордера: Наклон SMA вырос до {slope_pct:.3f}% > {max_slope}% "
                f"(микро-тренд начался после выставления ордера)"
            )
            trade_logger.info(
                f"⚪ ОТМЕНА {state['order_side'].upper()} | Причина: SMA Slope {slope_pct:.3f}% > {max_slope}%"
            )
            exchange.cancel_order(state["active_order_id"])
            state.update({
                "active_order_id": None, "order_side": None,
                "current_trigger_price": 0.0, "order_creation_time": 0.0,
                "channel_width_at_order_open": 0.0
            })
            return

    trail_pct = state.get("adaptive_trail_pct", config.TRAIL_PERCENT)
    price = state["current_price"]
    side = state["order_side"]
    trigger = state["current_trigger_price"]
    new_trigger = None
    safety_margin = 0.0005

    if side == "Sell":
        ideal = price * (1 - trail_pct / 100)
        if ideal > trigger and ideal < price * (1 - safety_margin):
            new_trigger = ideal
    else:
        ideal = price * (1 + trail_pct / 100)
        if ideal < trigger and ideal > price * (1 + safety_margin):
            new_trigger = ideal

    if new_trigger:
        state["current_trigger_price"] = new_trigger
        sl_pct = state.get("adaptive_sl_pct", config.SL_PERCENT)
        tp_pct = state.get("adaptive_tp_pct", config.TP_PERCENT)
        new_sl = new_trigger * (1 + sl_pct / 100) if side == "Sell" else new_trigger * (1 - sl_pct / 100)
        new_tp = new_trigger * (1 - tp_pct / 100) if side == "Sell" else new_trigger * (1 + tp_pct / 100)
        state["active_sl"] = new_sl
        state["active_tp"] = new_tp

        if time.time() - last_trail_log_time > 5.0:
            direction = 'ВВЕРХ 📈' if side == 'Sell' else 'ВНИЗ 📉'
            logger_main.info(f"🏃 Трейлинг ({side}) {direction}... Триггер: {new_trigger:.8f} (Trail: {trail_pct:.3f}%)")
            last_trail_log_time = time.time()

        success, error_code, msg = exchange.amend_order(state["active_order_id"], new_trigger, new_sl, new_tp)
        if error_code == 110001:
            # Ордер не существует на бирже — проверяем, не исполнился ли он уже
            logger_main.warning(f"⚠️ Ордер не существует (110001). Синхронизация с биржей...")
            pos_size, pos_side = exchange.get_position()
            if pos_size > 0:
                logger_main.info(f"🔄 Ордер уже исполнен биржей. Переход в позицию.")
                # sync_state() подхватит позицию на следующем тике
            else:
                logger_main.info("🏁 Ордер был отменен биржей. Сброс стейта.")
                state.update({
                    "active_order_id": None, "order_side": None,
                    "current_trigger_price": 0.0, "order_creation_time": 0.0,
                    "channel_width_at_order_open": 0.0
                })
        elif not success:
            logger_main.warning(f"⚠️ Трейлинг отклонен: {msg}")


def check_signal():
    if state["active_order_id"] or state["is_in_position"]:
        return
    if state.get("is_placing_order", False):
        return
    cooldown = getattr(config, 'TRADE_COOLDOWN_SECONDS', 60)
    if time.time() - state["last_trade_close_time"] < cooldown:
        return

    price = state["current_price"]
    upper = state["upper_bb"]
    lower = state["lower_bb"]
    if upper == 0.0 or lower == 0.0:
        return

    slope_pct = calculate_sma_slope()
    max_slope = getattr(config, 'MAX_SMA_SLOPE_PERCENT', 0.15)
    if slope_pct > max_slope:
        # Троттлинг: тикер приходит несколько раз в секунду, без него лог забивается
        _log_throttle("skip_slope", f"⚠️ Пропуск: Наклон SMA={slope_pct:.3f}% > {max_slope}%. Микро-тренд.")
        return

    channel_width_pct = ((upper - lower) / price * 100) if price > 0 else 0.0
    if channel_width_pct < config.MIN_CHANNEL_WIDTH_PERCENT:
        return
    if channel_width_pct > config.MAX_CHANNEL_WIDTH_PERCENT:
        _log_throttle("skip_channel", f"⚠️ Пропуск: Канал слишком широкий ({channel_width_pct:.2f}% > {config.MAX_CHANNEL_WIDTH_PERCENT}%).")
        return

    rvol = filters.calculate_rvol(state["current_candle_volume"], state["closed_volumes"])
    if rvol > config.MAX_RVOL_FOR_REVERSAL:
        _log_throttle("skip_rvol", f"⚠️ Пропуск: Аномальный объем RVOL={rvol:.2f}.")
        return

    if not filters.check_min_volatility(state["current_candle_range"], state["closed_ranges"], config.MIN_VOLATILITY_RATIO):
        return

    trail_pct, sl_pct, tp_pct = calculate_adaptive_params(channel_width_pct)

    if price > upper:
        if not filters.check_direction_reset(state["last_trade_direction"], "Sell", state["last_trade_candle_time"], state["closes"], config.BB_LENGTH):
            _log_throttle("ban_sell", "⚠️ Запрет на повторную продажу: цена не закрывалась ниже SMA.")
            return
        logger_main.info(f"🚀 Сигнал на Sell. RVOL: {rvol:.2f}, Slope: {slope_pct:.3f}%, Trail: {trail_pct:.3f}%")
        place_order_logic("Sell", price * (1 - trail_pct / 100), trail_pct, sl_pct, tp_pct)

    elif price < lower:
        if not filters.check_direction_reset(state["last_trade_direction"], "Buy", state["last_trade_candle_time"], state["closes"], config.BB_LENGTH):
            _log_throttle("ban_buy", "⚠️ Запрет на повторную покупку: цена не закрывалась выше SMA.")
            return
        logger_main.info(f"🚀 Сигнал на Buy. RVOL: {rvol:.2f}, Slope: {slope_pct:.3f}%, Trail: {trail_pct:.3f}%")
        place_order_logic("Buy", price * (1 + trail_pct / 100), trail_pct, sl_pct, tp_pct)


# ==============================================================================
# 6.1 Проверка "застоявшейся" позиции
# ==============================================================================
def check_stale_position():
    if not state["is_in_position"]:
        return
    if not getattr(config, 'ENABLE_STALE_TRADE_CLOSE', False):
        return

    candles = state.get("candles_since_open", [])
    timeout = config.STALE_TRADE_TIMEOUT_CANDLES
    if len(candles) < timeout:
        return

    recent_candles = candles[-timeout:]
    if len(state["closes"]) < config.BB_LENGTH:
        return

    closes = [c['close'] for c in state["closes"][-config.BB_LENGTH:]]
    sma = sum(closes) / config.BB_LENGTH
    crossed_sma = False

    for i, c in enumerate(recent_candles):
        side = state["position_side"]
        if side == "Buy" and c['close'] > sma:
            crossed_sma = True
            logger_main.info(f"✅ Свеча #{i + 1} закрылась выше SMA ({c['close']:.8f} > {sma:.8f})")
            break
        elif side == "Sell" and c['close'] < sma:
            crossed_sma = True
            logger_main.info(f"✅ Свеча #{i + 1} закрылась ниже SMA ({c['close']:.8f} < {sma:.8f})")
            break

    if not crossed_sma:
        logger_main.info(
            f"⚡ Принудительное закрытие: позиция застоялась "
            f"({timeout} свечей без пересечения SMA {sma:.8f})"
        )
        state["is_force_closing"] = True
        exchange.close_position(state["position_side"])
    else:
        state["candles_since_open"] = []
        logger_main.info(f"✅ Свеча пересекла SMA. Счетчик застоя сброшен.")


# ==============================================================================
# 6.2 Обработчик закрытия позиции в симуляторе
# ==============================================================================
def on_position_closed(side, exit_price, reason):
    if not state["is_in_position"]:
        return
    log_position_close(side, exit_price, reason)


# ==============================================================================
# 7. WEBSOCKET ОБРАБОТЧИКИ
# ==============================================================================
def on_price_update(message):
    try:
        data = json.loads(message)
        if data.get('op') == 'ping':
            return
        if 'topic' in data and f"tickers.{config.SYMBOL}" in data['topic']:
            if 'data' in data and 'lastPrice' in data['data']:
                state["current_price"] = float(data['data']['lastPrice'])
                if state["active_order_id"]:
                    trail_order_logic()
                else:
                    check_signal()
    except Exception as e:
        logger_main.error(f"❌ Ошибка обработки тикера: {e}")


def on_kline_update(message):
    try:
        data = json.loads(message)
        if 'topic' in data and f"kline.{config.TIMEFRAME}.{config.SYMBOL}" in data['topic'] and 'data' in data:
            candle = data['data'][0] if isinstance(data['data'], list) else data['data']
            if all(k in candle for k in ['close', 'start', 'volume', 'high', 'low']):
                close_price = float(candle['close'])
                high_price = float(candle['high'])
                low_price = float(candle['low'])
                volume = float(candle['volume'])
                candle_time = int(candle['start'])
                current_range = high_price - low_price

                if state["closes"] and state["closes"][-1]['time'] == candle_time:
                    state["closes"][-1].update({'close': close_price, 'high': high_price, 'low': low_price})
                    state["current_candle_volume"] = volume
                    state["current_candle_range"] = current_range
                else:
                    if state["closes"]:
                        state["closed_volumes"].append(state["current_candle_volume"])
                        if len(state["closed_volumes"]) > config.RVOL_PERIOD:
                            state["closed_volumes"].pop(0)
                        state["closed_ranges"].append(state["current_candle_range"])
                        if len(state["closed_ranges"]) > config.RVOL_PERIOD:
                            state["closed_ranges"].pop(0)

                        state["closes"].append({'time': candle_time, 'close': close_price, 'high': high_price, 'low': low_price})

                        if state["is_in_position"] and getattr(config, 'FORCE_CLOSE_AT_OPPOSITE_BAND', False):
                            upper = state["upper_bb"]
                            lower = state["lower_bb"]
                            if upper > 0.0 and lower > 0.0:
                                force_close = False
                                if state["position_side"] == "Buy" and high_price >= upper:
                                    force_close = True
                                    logger_main.info(f"⚡ Force Close (kline): high {high_price:.8f} >= upper {upper:.8f}")
                                elif state["position_side"] == "Sell" and low_price <= lower:
                                    force_close = True
                                    logger_main.info(f"⚡ Force Close (kline): low {low_price:.8f} <= lower {lower:.8f}")
                                if force_close:
                                    trade_logger.info(
                                        f"⚡ ПРИНУДИТЕЛЬНОЕ ЗАКРЫТИЕ (kline) {state['position_side'].upper()} |  "
                                        f"High: {high_price:.8f} | Low: {low_price:.8f} | Upper: {upper:.8f} | Lower: {lower:.8f}"
                                    )
                                    state["is_force_closing"] = True
                                    exchange.close_position(state["position_side"])
                                    return

                        if state["is_in_position"]:
                            state["candles_since_open"].append({
                                'time': candle_time, 'close': close_price,
                                'high': high_price, 'low': low_price
                            })
                            logger_main.info(f"📊 Свеча #{len(state['candles_since_open'])} добавлена. Close: {close_price:.8f}")
                            check_stale_position()

                        if len(state["closes"]) > config.BB_LENGTH + 20:
                            state["closes"].pop(0)

                        state.update({
                            "current_candle_volume": volume,
                            "current_candle_range": current_range,
                            "last_candle_time": candle_time
                        })
                    else:
                        state["closes"].append({'time': candle_time, 'close': close_price, 'high': high_price, 'low': low_price})
                        state.update({
                            "current_candle_volume": volume,
                            "current_candle_range": current_range,
                            "last_candle_time": candle_time
                        })

                calculate_bb()
    except Exception as e:
        logger_main.error(f"❌ Ошибка обработки свечи: {e}")


def on_order_update(message):
    try:
        data = json.loads(message)
        if data.get('op') == 'auth' and data.get('success'):
            exchange.ws_private.send(json.dumps({"op": "subscribe", "args": ["order"]}))
            return
        if data.get('topic') == 'order':
            for order in data.get('data', []):
                if order.get('symbol') != config.SYMBOL:
                    continue
                status = order.get('orderStatus')
                # Среднюю цену входа и фактический размер берём из WS-апдейта ордера —
                # это точные данные биржи (avgPrice по исполнению), без задержки REST-поллинга
                avg_px = 0.0
                try:
                    avg_px = float(order.get('avgPrice', 0) or 0)
                except (ValueError, TypeError):
                    pass
                filled_qty = 0.0
                try:
                    filled_qty = float(order.get('cumExecQty', 0) or 0)
                except (ValueError, TypeError):
                    pass

                if order.get('orderId') == state["active_order_id"]:
                    logger_main.info(f"📋 WS Ордер: {status}")
                    if status in ["Triggered", "Filled", "PartiallyFilled"]:
                        # Запись в trade_logger делает sync_state() — здесь обновляем стейт точными данными
                        if avg_px > 0:
                            state["entry_price"] = avg_px
                        if filled_qty > 0:
                            state["lot_size"] = filled_qty
                        state.update({"active_order_id": None, "is_in_position": True})
                    elif status in ["Cancelled", "Rejected", "Deactivated"]:
                        logger_main.info("❌ Ордер отменен/деактивирован.")
                        state.update({
                            "active_order_id": None, "order_side": None,
                            "current_trigger_price": 0.0, "order_creation_time": 0.0,
                            "channel_width_at_order_open": 0.0
                        })
                elif status in ["Completed", "Trade", "Filled"] and avg_px > 0:
                    # Срабатывание SL/TP на стороне позиции — фиксируем фактическую цену выхода
                    if state["is_in_position"]:
                        state["last_ws_exit_price"] = avg_px
                        state["last_ws_exit_time"] = time.time()
                        if filled_qty > 0:
                            state["lot_size"] = filled_qty
    except Exception as e:
        logger_main.error(f"❌ Ошибка обработки ордера: {e}")


# ==============================================================================
# 8. ГЛАВНЫЙ ЗАПУСК
# ==============================================================================
def main():
    # ВАЖНО: без `global shutdown_requested` здесь любой read (while not ...) или
    # write внутри main() трактуется Python как обращение к ЛОКАЛЬНОЙ переменной,
    # т.к. ниже по телу функции есть присваивание (except KeyboardInterrupt).
    # Это давало UnboundLocalError на первом же проходе цикла.
    global last_dashboard_time, shutdown_requested
    adaptive_tag = "ADAPTIVE" if getattr(config, 'ADAPTIVE_MODE', False) else "FIXED"
    logger_main.info(f"⚡ Бот v34.0 ({adaptive_tag}) запущен для {config.SYMBOL}")
    logger_main.info(f"📄 Лог сделок: {active_log_file}")

    trade_logger.info(
        f"🟢 МОНИТОРИНГ | Бот запущен | Режим: {'SIM' if config.SIMULATOR_MODE else 'LIVE'} | "
        f"{config.SYMBOL} {config.TIMEFRAME} | {adaptive_tag}"
    )

    exchange.register_callback('on_price', on_price_update)
    exchange.register_callback('on_kline', on_kline_update)
    exchange.register_callback('on_order', on_order_update)

    if config.SIMULATOR_MODE:
        exchange.register_callback('on_position_closed', on_position_closed)

    # Подтягивание позиции при старте (только для Live)
    pos_size, pos_side = exchange.get_position()
    if pos_size > 0:
        if not config.SIMULATOR_MODE and hasattr(exchange, 'rest'):
            try:
                res = exchange.rest.get_positions(category=config.CATEGORY, symbol=config.SYMBOL)
                for pos in res['result']['list']:
                    if pos['symbol'] == config.SYMBOL and float(pos['size']) > 0:
                        real_entry = float(pos.get('avgPrice', 0))
                        real_size = float(pos['size'])
                        state.update({
                            "is_in_position": True,
                            "position_side": pos_side,
                            "entry_price": real_entry,
                            "lot_size": int(real_size),
                            "initial_balance": exchange.get_balance()
                        })
                        logger_main.info(f"🔄 Обнаружена позиция при старте: {pos_side} @ {real_entry:.8f}, Лот: {int(real_size)}")
                        break
            except Exception as e:
                logger_main.error(f"❌ Ошибка подтягивания позиции при старте: {e}")
                state.update({"is_in_position": True, "position_side": pos_side, "initial_balance": exchange.get_balance()})
        else:
            state.update({"is_in_position": True, "position_side": pos_side, "initial_balance": exchange.get_balance()})
    else:
        state["initial_balance"] = exchange.get_balance()

    candles = exchange.get_klines(config.BB_LENGTH + 20)
    if not candles or len(candles) == 0:
        logger_main.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Биржа не вернула свечи для {config.SYMBOL}.")
        return

    state["closes"] = candles
    for i in range(len(candles) - 1):
        state["closed_volumes"].append(0.0)
        state["closed_ranges"].append(candles[i]['high'] - candles[i]['low'])

    calculate_bb()
    calculate_sma_slope()
    logger_main.info(f"✅ Успешно загружено {len(candles)} свечей. Запуск WebSocket...")
    exchange.start_websockets()
    print_dashboard()

    # Graceful shutdown по сигналу: менеджер останавливает бота через SIGTERM
    # (Windows: CTRL_BREAK_EVENT). Без обработчика процесс умирал мгновенно,
    # а main-цикл не закрывал WS — потоки переподключения продолжали сыпать
    # ошибками в startup_error.log уже после «остановки» бота.
    import signal

    def _handle_stop_signal(signum, frame):
        global shutdown_requested
        shutdown_requested = True
        try:
            exchange.shutdown_requested = True
        except Exception:
            pass

    for _sig in (signal.SIGTERM, getattr(signal, 'SIGBREAK', signal.SIGTERM)):
        try:
            signal.signal(_sig, _handle_stop_signal)
        except (ValueError, OSError, AttributeError):
            pass

    try:
        while not shutdown_requested:
            time.sleep(0.5)
            if shutdown_requested:
                break
            sync_state()
            dashboard_interval = getattr(config, 'DASHBOARD_UPDATE_INTERVAL', 5.0)
            if time.time() - last_dashboard_time > dashboard_interval:
                last_dashboard_time = time.time()
                print_dashboard()
    except KeyboardInterrupt:
        shutdown_requested = True
    finally:
        logger_main.info("🛑 Остановка...")
        try:
            exchange.cancel_order(state.get("active_order_id"))
        except Exception as e:
            logger_main.error(f"Ошибка при отмене ордера: {e}")
        try:
            exchange.stop_websockets()
        except Exception as e:
            logger_main.error(f"Ошибка при остановке WS: {e}")
        # Короткая пауза, чтобы буферы лог-хендлеров сбросились до выхода процесса
        time.sleep(0.2)
        logger_main.info("🛑 Бот остановлен корректно.")


if __name__ == "__main__":
    main()
