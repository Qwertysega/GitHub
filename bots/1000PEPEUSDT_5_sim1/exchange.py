import time
import json
import hmac
import hashlib
import logging
import websocket
import threading
import config

from pybit.unified_trading import HTTP

logger = logging.getLogger(__name__)

# Демо-режим (торговля на api-demo.bybit.com). Значение берётся из config.py,
# по умолчанию — True (исторически бот работает только с демо-ключами).
DEMO_TRAADING = getattr(config, 'DEMO_TRADING', True)

# Системные константы с дефолтами на случай отсутствия в конфиге.
# ВАЖНО: у Bybit демо-окружение изолировано ТОЛЬКО для приватных (торговых) потоков:
#   REST:  api-demo.bybit.com (существует),
#   PRIVATE WS: wss://stream-demo.bybit.com/v5/private — ДА, только stream-demo!
#   PUBLIC WS:  публичные топики (tickers/kline) обслуживаются ОБЫЧНЫМ доменом
#   wss://stream.bybit.com/v5/public/linear даже для демо-аккаунтов. На
#   stream-demo по пути /v5/public/linear сервер возвращает Handshake 404
#   (проверено живым соединением). Ошибка прошлой ревизии — отправлять public
#   WS на stream-demo: это и давало лавину "Handshake status 404 Not Found".
if DEMO_TRAADING:
    _DEFAULT_WS_PUBLIC = "wss://stream.bybit.com/v5/public/linear"
    _DEFAULT_WS_PRIVATE = "wss://stream-demo.bybit.com/v5/private"
else:
    _DEFAULT_WS_PUBLIC = "wss://stream.bybit.com/v5/public/linear"
    _DEFAULT_WS_PRIVATE = "wss://stream.bybit.com/v5/private"

WS_PUBLIC_URL = getattr(config, 'WS_PUBLIC_URL', _DEFAULT_WS_PUBLIC)
WS_PRIVATE_URL = getattr(config, 'WS_PRIVATE_URL', _DEFAULT_WS_PRIVATE)


def _looks_like_demo_key(api_key: str) -> bool:
    """Демо-токены Bybit обычно имеют префикс 'demo' (напр. dguX... или demoXXXX)."""
    return bool(api_key) and api_key.lower().startswith("demo")


def _fix_ws_urls_for_mode(public_url: str, private_url: str, demo: bool):
    """Приводит WS-эндпоинты в соответствие с режимом DEMO_TRADING.

    Правила (подтверждены живыми проверками соединения):
      * Public WS — ВСЕГДА обычный домен stream.bybit.com (в т.ч. в демо);
        если config.py указывает public на stream-demo (баг старых версий) —
        переписываем обратно, иначе получаем Handshake 404 от CloudFront.
      * Private WS — в демо обязан быть на stream-demo.bybit.com; демо-ключи
        на обычном stream.bybit.com авторизуются с 401 "API key is invalid".
    """
    # 1) Public: нормализуем к обычному домену в обоих режимах
    if public_url and "stream-demo.bybit.com" in public_url:
        new_public = public_url.replace("stream-demo.bybit.com", "stream.bybit.com")
    else:
        new_public = public_url or _DEFAULT_WS_PUBLIC

    # 2) Private: синхронизируем домен с режимом
    if demo:
        if private_url and "stream-demo.bybit.com" not in private_url and "stream.bybit.com" in private_url:
            new_private = private_url.replace("stream.bybit.com", "stream-demo.bybit.com")
        else:
            new_private = private_url or _DEFAULT_WS_PRIVATE
    else:
        if private_url and "stream-demo.bybit.com" in private_url:
            new_private = private_url.replace("stream-demo.bybit.com", "stream.bybit.com")
        else:
            new_private = private_url or _DEFAULT_WS_PRIVATE

    if (new_public, new_private) != (public_url, private_url):
        logger.warning(
            f"🔧 WS URL не соответствовали режиму DEMO_TRADING={demo} — "
            f"исправлено автоматически: public={new_public} | private={new_private}"
        )
    return new_public, new_private


class BybitClient:
    def __init__(self):
        global WS_PUBLIC_URL, WS_PRIVATE_URL

        # Ключи и эндпоинты должны соответствовать друг другу:
        # демо-ключ -> api-demo/stream-demo, основной ключ -> api/stream.
        if not DEMO_TRAADING and _looks_like_demo_key(config.API_KEY):
            logger.warning(
                "⚠️ DEMO_TRADING=False, но API_KEY похож на демо-токен: "
                "запросы к основному API вернут 401. Включите демо-режим в настройках."
            )

        # Синхронизируем WS-домены с режимом (защита от устаревших URL в config.py)
        WS_PUBLIC_URL, WS_PRIVATE_URL = _fix_ws_urls_for_mode(
            WS_PUBLIC_URL, WS_PRIVATE_URL, DEMO_TRAADING
        )

        self.ws_public_url = WS_PUBLIC_URL
        self.ws_private_url = WS_PRIVATE_URL

        self.rest = HTTP(
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
            demo=DEMO_TRAADING,
            recv_window=15000
        )
        self.ws_public = None
        self.ws_private = None
        self.callbacks = {}
        self.ws_status = "🔴 Отключено"
        self.current_bid = 0.0
        self.current_ask = 0.0
        self.point = getattr(config, 'TICK_SIZE', 0.01)
        self._auth_error_logged = False
        self._error_throttle: dict = {}
        # Флаг graceful shutdown (выставляет bot.py): WS-циклы переподключения
        # проверяют его и завершаются, а не крутят ошибки после остановки бота.
        self.shutdown_requested = False

    def _log_auth_hint(self, exc: Exception):
        """Однострочная подсказка при 401 — чтобы не спамить в лог каждые 2 секунды."""
        text = str(exc)
        if "401" in text or "not authorized" in text.lower():
            if not self._auth_error_logged:
                self._auth_error_logged = True
                logger.error(
                    "❌ 401 Unauthorized: демо-ключи (api-demo.bybit.com) НЕ работают с основным "
                    "API и наоборот. Проверьте: 1) ключ создан именно в Демо-трейдинге "
                    "(Bybit → Профиль → Демо-трейдинг → Управление API), а не в обычном кабинете; "
                    "2) у ключа включены чтения баланса/позиций и торговля; "
                    "3) DEMO_TRADING в config.py соответствует типу ключа."
                )

    def _log_recurring_error(self, key: str, message: str, interval: float = 60.0):
        """
        Троттлинг повторяющихся REST-ошибок (401/таймауты). sync_state() дергает
        баланс/позиции каждые ~2 сек, а тикер-стрим — несколько раз в секунду,
        поэтому без ограничения частоты лог забивается одинаковыми строками.
        Первая ошибка пишется сразу, далее — не чаще одного раза в `interval` сек.
        """
        now = time.time()
        last = self._error_throttle.get(key, 0.0)
        if now - last < interval:
            return
        self._error_throttle[key] = now
        logger.error(message)

    def register_callback(self, event_name, func):
        self.callbacks[event_name] = func

    def get_balance(self):
        try:
            res = self.rest.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            if res.get('retCode') != 0:
                logger.error(f"Ошибка API баланса: {res.get('retMsg')}")
                return 0.0
            coin_list = res.get('result', {}).get('list', [{}])[0].get('coin', [])
            for c in coin_list:
                if c.get('coin') == 'USDT':
                    return float(c.get('walletBalance', 0.0))
            return 0.0
        except Exception as e:
            self._log_recurring_error("balance", f"Ошибка баланса: {e}")
            self._log_auth_hint(e)
            return 0.0

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
            logger.error(f"Ошибка свечей: {e}")
            return []

    def get_position(self):
        try:
            res = self.rest.get_positions(category=config.CATEGORY, symbol=config.SYMBOL)
            for pos in res['result']['list']:
                if pos['symbol'] == config.SYMBOL:
                    return float(pos['size']), pos['side']
            return 0.0, None
        except Exception as e:
            self._log_recurring_error("position", f"Ошибка позиции: {e}")
            self._log_auth_hint(e)
            return 0.0, None

    def get_position_data(self):
        """Полные данные позиции с биржи: размер, сторона, средняя цена входа, realizedPnl."""
        try:
            res = self.rest.get_positions(category=config.CATEGORY, symbol=config.SYMBOL)
            for pos in res['result']['list']:
                if pos['symbol'] == config.SYMBOL and float(pos.get('size', 0)) > 0:
                    return {
                        "size": float(pos['size']),
                        "side": pos.get('side') or None,
                        "avg_price": float(pos.get('avgPrice', 0) or 0),
                        "realized_pnl": float(pos.get('realizedPnl', 0) or 0),
                        "position_idx": int(pos.get('positionIdx', 0) or 0),
                    }
            return {"size": 0.0, "side": None, "avg_price": 0.0,
                    "realized_pnl": 0.0, "position_idx": 0}
        except Exception as e:
            self._log_recurring_error("position_data", f"Ошибка получения данных позиции: {e}")
            self._log_auth_hint(e)
            return {"size": -1.0, "side": None, "avg_price": 0.0,
                    "realized_pnl": 0.0, "position_idx": 0}

    def get_recent_executions(self, limit=20):
        """Реальные исполнения (fills) по символу за последние ~15 минут, в хронологическом порядке."""
        try:
            start_ms = int((time.time() - 900) * 1000)
            # В pybit метод называется get_executions (v5 /order/execution)
            res = self.rest.get_executions(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                startTime=start_ms,
                limit=limit
            )
            execs = []
            for e in res.get('result', {}).get('list', []):
                try:
                    execs.append({
                        "exec_id": e.get('execId', ''),
                        "price": float(e.get('execPrice', 0) or 0),
                        "qty": float(e.get('execQty', 0) or 0),
                        "fee": float(e.get('execFee', 0) or 0),
                        "side": e.get('side'),
                        "is_maker": str(e.get('isMaker', '')) == 'true',
                        "created_ms": int(e.get('tradeTime' if 'tradeTime' in e else 'executedTs', 0) or 0),
                    })
                except (ValueError, TypeError):
                    continue
            # Bybit отдаёт в обратном хронологии — приводим к возрастанию времени
            execs.sort(key=lambda x: x["created_ms"])
            return execs
        except Exception as e:
            logger.error(f"Ошибка получения исполнений: {e}")
            self._log_auth_hint(e)
            return []

    def check_order_exists(self, order_id):
        if not order_id:
            return False
        try:
            res = self.rest.get_open_orders(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                orderId=order_id
            )
            return len(res['result']['list']) > 0
        except Exception:
            return False

    def get_spread(self):
        return self.current_ask - self.current_bid if self.current_ask > 0 else 0.0

    def place_order(self, side, trigger_price, sl, tp, lot_size, sma_slope=0.0):
        try:
            position_idx = 1 if side == "Buy" else 2
            direction = 1 if side == "Buy" else 2
            res = self.rest.place_order(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                side=side,
                orderType="Market",
                qty=str(lot_size),
                triggerPrice=str(round(trigger_price, 8)),
                triggerDirection=direction,
                positionIdx=position_idx,
                stopLoss=str(round(sl, 8)),
                takeProfit=str(round(tp, 8)),
                triggerBy="LastPrice",
                timeInForce="GTC",
                reduceOnly=False
            )
            if res['retCode'] == 0:
                return res['result']['orderId']
            logger.error(f"Ошибка создания ордера: {res['retMsg']}")
            return None
        except Exception as e:
            logger.error(f"Исключение ордера: {e}")
            return None

    def amend_order(self, order_id, new_trigger, new_sl, new_tp):
        try:
            res = self.rest.amend_order(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                orderId=order_id,
                triggerPrice=str(round(new_trigger, 8)),
                stopLoss=str(round(new_sl, 8)),
                takeProfit=str(round(new_tp, 8))
            )
            return res['retCode'] == 0, res.get('retCode', 0), res.get('retMsg', '')
        except Exception as e:
            logger.error(f"Ошибка трейлинга: {e}")
            return False, -1, str(e)

    def cancel_order(self, order_id):
        if not order_id:
            return
        try:
            res = self.rest.cancel_order(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                orderId=order_id
            )
            if res['retCode'] == 0:
                logger.info(f"✅ Ордер {order_id} отменен.")
        except Exception as e:
            logger.error(f"Ошибка отмены: {e}")

    def close_position(self, side):
        try:
            pos_size, pos_side = self.get_position()
            if pos_size <= 0:
                logger.warning("⚠️ Позиция уже закрыта или не существует")
                return True
            close_side = "Sell" if side == "Buy" else "Buy"
            position_idx = 1 if pos_side == "Buy" else 2 if pos_side == "Sell" else 0
            res = self.rest.place_order(
                category=config.CATEGORY,
                symbol=config.SYMBOL,
                side=close_side,
                orderType="Market",
                qty=str(pos_size),
                positionIdx=position_idx,
                reduceOnly=True,
                timeInForce="GTC"
            )
            if res['retCode'] == 0:
                logger.info(f"✅ Позиция принудительно закрыта! Order ID: {res['result']['orderId']}")
                return True
            logger.error(f"❌ Ошибка закрытия позиции: {res['retMsg']} (код: {res['retCode']})")
            return False
        except Exception as e:
            logger.error(f"❌ Исключение при закрытии позиции: {e}")
            return False

    # === WebSocket обработчики ===

    def _on_public_msg(self, ws, message):
        self.ws_status = "🟢 Public OK"
        try:
            data = json.loads(message)
            if data.get('op') == 'ping':
                ws.send(json.dumps({'op': 'pong'}))
                return
            if 'topic' in data and 'tickers.' in data['topic'] and 'data' in data:
                d = data['data']
                if 'bid1Price' in d and 'ask1Price' in d:
                    self.current_bid = float(d['bid1Price'])
                    self.current_ask = float(d['ask1Price'])
            if 'on_price' in self.callbacks:
                self.callbacks['on_price'](message)
            if 'on_kline' in self.callbacks:
                self.callbacks['on_kline'](message)
        except Exception:
            pass

    def _on_private_msg(self, ws, message):
        self.ws_status = "🟢 Private OK"
        if 'on_order' in self.callbacks:
            self.callbacks['on_order'](message)

    def _on_public_open(self, ws):
        """Вызывается ПОСЛЕ установки соединения."""
        self.ws_status = "🟢 Public Connected"
        logger.info(f"🌐 Public WS подключен для {config.SYMBOL}")
        ws.send(json.dumps({
            "op": "subscribe",
            "args": [f"tickers.{config.SYMBOL}"]
        }))
        ws.send(json.dumps({
            "op": "subscribe",
            "args": [f"kline.{config.TIMEFRAME}.{config.SYMBOL}"]
        }))

    def _on_private_open(self, ws):
        """Вызывается ПОСЛЕ установки соединения. Сначала авторизация, потом подписка."""
        self.ws_status = "🟢 Private Connected"
        logger.info("🔑 Private WS подключен, авторизация...")
        expires = int((time.time() + 10) * 1000)
        signature = hmac.new(
            config.API_SECRET.encode('utf-8'),
            f"GET/realtime{expires}".encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        ws.send(json.dumps({
            "op": "auth",
            "args": [config.API_KEY, expires, signature]
        }))

    def _on_private_auth_response(self, ws, message):
        """Обрабатывает ответ авторизации и подписывается на ордера только после успеха."""
        try:
            data = json.loads(message)
            if data.get('op') == 'auth':
                if data.get('success'):
                    logger.info("✅ Авторизация Private WS успешна")
                    ws.send(json.dumps({
                        "op": "subscribe",
                        "args": ["order"]
                    }))
                else:
                    logger.error(f"❌ Авторизация Private WS не удалась: {data.get('retMsg', 'Unknown error')}")
                return
        except Exception:
            pass
        # Передаём дальше в обычный обработчик
        self._on_private_msg(ws, message)

    def start_websockets(self):
        def run_public_ws():
            while not self.shutdown_requested:
                try:
                    self.ws_public = websocket.WebSocketApp(
                        self.ws_public_url,
                        on_message=self._on_public_msg,
                        on_open=self._on_public_open,
                        on_close=lambda ws, code, msg: setattr(self, 'ws_status', "🔴 Public Disconnected"),
                        on_error=self._on_ws_error_public
                    )
                    self.ws_public.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    if self.shutdown_requested:
                        break
                    logger.warning(f"⚠️ Public WS разорван: {e}. Переподключение через 3с...")
                    setattr(self, 'ws_status', "🔄 Reconnecting...")
                    # Короткие срезы сна — поток мгновенно выходит при остановке бота
                    for _ in range(6):
                        if self.shutdown_requested:
                            return
                        time.sleep(0.5)

        def run_private_ws():
            while not self.shutdown_requested:
                try:
                    self.ws_private = websocket.WebSocketApp(
                        self.ws_private_url,
                        on_message=self._on_private_auth_response,
                        on_open=self._on_private_open,
                        on_close=lambda ws, code, msg: setattr(self, 'ws_status', "🔴 Private Disconnected"),
                        on_error=self._on_ws_error_private
                    )
                    self.ws_private.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    if self.shutdown_requested:
                        break
                    logger.warning(f"⚠️ Private WS разорван: {e}. Переподключение через 3с...")
                    setattr(self, 'ws_status', "🔄 Reconnecting...")
                    for _ in range(6):
                        if self.shutdown_requested:
                            return
                        time.sleep(0.5)

        threading.Thread(target=run_public_ws, daemon=True).start()
        threading.Thread(target=run_private_ws, daemon=True).start()

    def _on_ws_error_public(self, ws, error):
        """WS-ошибки публичного потока: троттлинг + выход при остановке бота."""
        if getattr(self, 'shutdown_requested', False):
            return
        self._log_recurring_error("public_ws", f"⚠️ Public WS ошибка: {error}", interval=30.0)

    def _on_ws_error_private(self, ws, error):
        if getattr(self, 'shutdown_requested', False):
            return
        self._log_recurring_error("private_ws", f"⚠️ Private WS ошибка: {error}", interval=30.0)

    def stop_websockets(self):
        # Сначала поднимаем флаг — циклы переподключения и on_error больше не спамят
        self.shutdown_requested = True
        try:
            if self.ws_public:
                self.ws_public.close()
        except Exception:
            pass
        try:
            if self.ws_private:
                self.ws_private.close()
        except Exception:
            pass
