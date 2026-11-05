import time
import json
from pathlib import Path
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError


class SymbolLoader:
    """
    Загрузка и кэширование фьючерсных пар с Bybit V5 API.
    Не зависит от PyQt6 — можно использовать в любом потоке.
    """

    BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000"
    CACHE_TTL_SECONDS = 3600  # 1 час

    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = cache_file or Path("symbols_cache.json")
        self._symbols: List[Dict[str, str]] = []
        self._last_loaded: float = 0.0

    def load_from_cache(self) -> bool:
        """Загружает символы из локального кэша, если он свежий."""
        if not self.cache_file.exists():
            return False
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if time.time() - data.get("updated_at", 0) > self.CACHE_TTL_SECONDS:
                return False
            self._symbols = data.get("symbols", [])
            self._last_loaded = data["updated_at"]
            return len(self._symbols) > 0
        except (json.JSONDecodeError, KeyError, OSError):
            return False

    def fetch_from_api(self) -> List[Dict[str, str]]:
        """
        Загружает символы напрямую с Bybit API.
        Возвращает список {"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "status": "Trading"}
        """
        try:
            req = Request(self.BYBIT_INSTRUMENTS_URL, headers={"User-Agent": "BotManager/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("retCode") != 0:
                raise ValueError(f"Bybit API error: {data.get('retMsg')}")

            instruments = data.get("result", {}).get("list", [])
            symbols = [
                {
                    "symbol": inst["symbol"],
                    "baseCoin": inst.get("baseCoin", ""),
                    "quoteCoin": inst.get("quoteCoin", ""),
                    "status": inst.get("status", ""),
                }
                for inst in instruments
                if inst.get("status") == "Trading" and inst.get("quoteCoin") == "USDT"
            ]

            # Сохраняем в кэш
            cache_data = {"symbols": symbols, "updated_at": time.time()}
            self.cache_file.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

            self._symbols = symbols
            self._last_loaded = time.time()
            return symbols

        except (URLError, ValueError, OSError, json.JSONDecodeError) as e:
            print(f"❌ Ошибка загрузки символов: {e}")
            # Fallback: пробуем загрузить из кэша даже если устарел
            if not self._symbols:
                self.load_from_cache()
            return self._symbols

    def get_symbols(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """Возвращает список символов. Использует кэш, если не принудительное обновление."""
        if force_refresh or not self._symbols:
            if not force_refresh and self.load_from_cache():
                return self._symbols
            return self.fetch_from_api()
        return self._symbols

    def search(self, query: str, limit: int = 50) -> List[Dict[str, str]]:
        """Поиск по символу или базовой монете. Регистронезависимый."""
        q = query.upper().strip()
        if not q:
            return self._symbols[:limit]
        results = [
            s for s in self._symbols
            if q in s["symbol"] or q in s["baseCoin"]
        ]
        return results[:limit]

    @property
    def last_updated(self) -> float:
        return self._last_loaded
