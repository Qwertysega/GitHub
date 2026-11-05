import time
import json
import logging
import websocket
import threading
import uuid
import config

from pybit.unified_trading import HTTP

logger = logging.getLogger(__name__)

# Системные константы с дефолтами.
# ВАЖНО: публичные топики Bybit (tickers/kline) ВСЕГДА живут на обычном домене
# wss://stream.bybit.com/v5/public/linear — и для демо-аккаунтов тоже. На
# stream-demo по пути /v5/public/linear соединение получает Handshake 404.
_DEFAULT_WS_PUBLIC = "wss://stream.bybit.com/v5/public/linear"

DEMO_TRAADING = getattr(config, 'DEMO_TRADING', True)

WS_PUBLIC_URL = getattr(config, 'WS_PUBLIC_URL', _DEFAULT_WS_PUBLIC)
# Защита от устаревших config.py, где public был ошибочно отправлен на stream-demo:
if WS_PUBLIC_URL and "stream-demo.bybit.com" in WS_PUBLIC_URL:
    WS_PUBLIC_URL = WS_PUBLIC_URL.replace("stream-demo.bybit.com", "stream.bybit.com")
    logger.warning(f"🔧 Simulator public WS URL исправлен на {WS_PUBLIC_URL}")


class SimulatorClient:
    def __init__(self):
        self.balance = config.SIMULATOR_BALANCE
        self.pending_orders = {}
        self.position = {"size": 0.0, "side": None, "entry_price": 0.0, "sl": 0.0, "tp": 0.0}
        self.current_bid = 0.0
        self.current_ask = 0.0
        self.last_price = 0.0
        self.commission_percent = config.SIMULATOR_COMMISSION_PERCENT
        # Адаптивный слиппедж: 0.02% от цены
        self.slippage_pct = 0.0002
        self.ws_public = None
        self.shutdown_requested = False
        # В симуляторе торгуем локально; REST нужен только для истории свечей
        # (публичный метод). demo-флаг синхронизирован с режимом ключей, чтобы
        # не ловить 401 при проверке авторизации на api-demo/api.bybit.com.
        self.rest = HTTP(api_key=config.API_KEY, api_secret=config.API_SECRET,
                         demo=DEMO_TRAADING, recv_window=15000)
        self.ws_status = "🔴 Отключено"
        self.callbacks = {}
        self.trade_logger = logging.getLogger("TradeHistory")

    def register_callback(self, event_name, func):
        self.callbacks[event_name] = func

    def get_balance(self):
        return self.balance

    def get_klines(self, limit):
        try:
            res = self.rest.get_kline(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                interval=config.TIMEFRAME,
                limit=limit
            )
            if res.get('retCode') != 0:
                logger.error(f"❌ Ошибка API Bybit: {res.get('retMsg')} (Код: {res.get('retCode')})")
                return []
            return [
                {
                    'time': int(c[0]),
                    'open': float(c[1]),
                    'high': float(c[2]),
                    'low': float(c[3]),
                    'close': float(c[4]),
                    'volume': float(c[5])
                }
                for c in reversed(res['result']['list'])
            ]
        except Exception as e:
            logger.error(f"❌ Исключение при загрузке свечей: {e}")
            return []

    def get_position(self):
        return self.position["size"], self.position["side"]

    def check_order_exists(self, order_id):
        return order_id in self.pending_orders

    def get_spread(self):
        return self.current_ask - self.current_bid if self.current_ask > 0 else 0.0

    def place_order(self, side, trigger_price, sl, tp, lot_size, sma_slope=0.0):
        order_id = str(uuid.uuid4())
        self.pending_orders[order_id] = {
            "side": side,
            "trigger_price": trigger_price,
            "sl": sl,
            "tp": tp,
            "qty": lot_size,
            "sma_slope": sma_slope,
            "logged_execution": False
        }
        logger.info(f"🎮 [SIM] Ордер создан: {side} @ {trigger_price:.8f}, Лот: {lot_size} (ID: {order_id[:8]})")
        return order_id

    def amend_order(self, order_id, new_trigger, new_sl, new_tp):
        if order_id in self.pending_orders:
            self.pending_orders[order_id]["trigger_price"] = new_trigger
            self.pending_orders[order_id]["sl"] = new_sl
            self.pending_orders[order_id]["tp"] = new_tp
            return True, 0, "OK"
        return False, 110001, "Order not found"

    def cancel_order(self, order_id):
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
            logger.info(f"[SIM] Ордер {order_id[:8]} отменен.")

    def close_position(self, side):
        if self.position["size"] == 0.0:
            return False
        exit_price = self.current_bid if side == "Buy" else self.current_ask
        if exit_price > 0:
            self._close_position(exit_price, "Opposite Band")
            return True
        return False

    def _process_market_tick(self):
        if self.current_bid == 0.0 or self.current_ask == 0.0:
            return

        # === Обработка отложенных ордеров ===
        orders_to_remove = []
        for oid, order in self.pending_orders.items():
            filled = False
            exec_price = 0.0

            # Исполнение по LastPrice (как на реальной бирже)
            last_p = self.last_price if self.last_price > 0 else self.current_bid

            if order["side"] == "Buy" and last_p >= order["trigger_price"]:
                filled = True
                exec_price = self.current_ask * (1 + self.slippage_pct)
            elif order["side"] == "Sell" and last_p <= order["trigger_price"]:
                filled = True
                exec_price = self.current_bid * (1 - self.slippage_pct)

            if filled and not order.get("logged_execution", False):
                slope_at_exec = order.get("sma_slope", 0.0)
                self.trade_logger.info(
                    f"⚡ ИСПОЛНЕНИЕ {order['side'].upper()} | Статус: Triggered (sim) |  "
                    f"Факт. цена: {exec_price:.8f} | Триггер: {order['trigger_price']:.8f} |  "
                    f"SL: {order['sl']:.8f} | TP: {order['tp']:.8f} |  "
                    f"SMA Slope: {slope_at_exec:.3f}%"
                )
                order["logged_execution"] = True
                self._open_position(order["side"], exec_price, order["sl"], order["tp"], order["qty"])
                orders_to_remove.append(oid)
                logger.info(f"[SIM] Ордер {oid[:8]} ИСПОЛНЕН по {exec_price:.8f}")

        for oid in orders_to_remove:
            del self.pending_orders[oid]

        # === Обработка SL/TP открытой позиции ===
        if self.position["size"] > 0:
            side = self.position["side"]
            sl = self.position["sl"]
            tp = self.position["tp"]
            closed = False
            exit_price = 0.0
            reason = ""

            if side == "Buy":
                if self.current_bid <= sl:
                    closed = True
                    exit_price = sl
                    reason = "Stop Loss"
                elif self.current_ask >= tp:
                    closed = True
                    exit_price = tp
                    reason = "Take Profit"
            else:
                if self.current_ask >= sl:
                    closed = True
                    exit_price = sl
                    reason = "Stop Loss"
                elif self.current_bid <= tp:
                    closed = True
                    exit_price = tp
                    reason = "Take Profit"

            if closed:
                self._close_position(exit_price, reason)

    def _open_position(self, side, exec_price, sl, tp, qty):
        self.position = {"size": qty, "side": side, "entry_price": exec_price, "sl": sl, "tp": tp}
        trade_volume = exec_price * qty
        comm = trade_volume * (self.commission_percent / 100.0)
        self.balance -= comm
        logger.info(f"[SIM] Позиция {side} открыта. Лот: {qty} | Комиссия: -{comm:.4f} USDT | Баланс: {self.balance:.2f}")

    def _close_position(self, exit_price, reason):
        side = self.position["side"]
        entry = self.position["entry_price"]
        qty = self.position["size"]
        pnl = (exit_price - entry) * qty if side == "Buy" else (entry - exit_price) * qty
        trade_volume = exit_price * qty
        comm = trade_volume * (self.commission_percent / 100.0)
        self.balance += pnl - comm
        self.position = {"size": 0.0, "side": None, "entry_price": 0.0, "sl": 0.0, "tp": 0.0}
        logger.info(
            f"[SIM] Позиция закрыта по {reason} @ {exit_price:.8f}. "
            f"Лот: {qty} | PnL: {pnl:+.4f} USDT | Комиссия: -{comm:.4f} USDT | "
            f"Чистый PnL: {pnl - comm:+.4f} USDT | Баланс: {self.balance:.2f}"
        )
        if 'on_position_closed' in self.callbacks:
            self.callbacks['on_position_closed'](side, exit_price, reason)

    def _on_public_msg(self, ws, message):
        self.ws_status = "🟢 Connected"
        try:
            data = json.loads(message)
            if data.get('op') == 'ping':
                ws.send(json.dumps({'op': 'pong'}))
                return
            if 'topic' in data and f"tickers.{config.SYMBOL}" in data['topic'] and 'data' in data:
                d = data['data']
                if 'bid1Price' in d and 'ask1Price' in d:
                    self.current_bid = float(d['bid1Price'])
                    self.current_ask = float(d['ask1Price'])
                if 'lastPrice' in d:
                    self.last_price = float(d['lastPrice'])
                self._process_market_tick()
            if 'on_price' in self.callbacks:
                self.callbacks['on_price'](message)
            if 'topic' in data and f"kline.{config.TIMEFRAME}.{config.SYMBOL}" in data['topic'] and 'data' in data:
                if 'on_kline' in self.callbacks:
                    self.callbacks['on_kline'](message)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга WS: {e}")

    def _on_public_open(self, ws):
        """Вызывается ПОСЛЕ установки соединения."""
        self.ws_status = "🟢 Connected"
        logger.info(f"🎮 [SIM] Подключен к публичному WS для {config.SYMBOL}")
        ws.send(json.dumps({"op": "subscribe", "args": [f"tickers.{config.SYMBOL}"]}))
        ws.send(json.dumps({"op": "subscribe", "args": [f"kline.{config.TIMEFRAME}.{config.SYMBOL}"]}))

    def start_websockets(self):
        def run_public_ws():
            while not getattr(self, 'shutdown_requested', False):
                try:
                    self.ws_public = websocket.WebSocketApp(
                        WS_PUBLIC_URL,
                        on_message=self._on_public_msg,
                        on_open=self._on_public_open,
                        on_close=lambda ws, code, msg: setattr(self, 'ws_status', "🔴 Disconnected"),
                        on_error=lambda ws, error: setattr(self, 'ws_status', "🔴 Error")
                    )
                    self.ws_public.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    if getattr(self, 'shutdown_requested', False):
                        break
                    logger.warning(f"⚠️ [SIM] WS разорван: {e}. Переподключение через 3с...")
                    setattr(self, 'ws_status', "🔄 Reconnecting...")
                    for _ in range(6):
                        if getattr(self, 'shutdown_requested', False):
                            return
                        time.sleep(0.5)

        threading.Thread(target=run_public_ws, daemon=True).start()

    def stop_websockets(self):
        self.shutdown_requested = True
        try:
            if self.ws_public:
                self.ws_public.close()
        except Exception:
            pass
