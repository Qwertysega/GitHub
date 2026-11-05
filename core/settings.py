import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "api_key": "",
    "api_secret": "",
    "demo_trading": True,
    "default_risk_per_trade": 10.0,
    "default_bb_length": 20,
    "default_bb_std_dev": 2.0,
    "default_adaptive_mode": True,
    "default_trail_percent": 0.2,
    "default_sl_percent": 0.6,
    "default_tp_percent": 1.2,
    "default_base_trail_percent": 0.2,
    "default_trail_growth_factor": 0.15,
    "default_sl_from_trail_percent": 120.0,
    "default_tp_from_width_percent": 80.0,
    "default_maker_fee_percent": 0.02,
    "default_taker_fee_percent": 0.055,
    "default_rvol_period": 20,
    "default_max_rvol_for_reversal": 500.0,
    "default_min_volatility_ratio": 0.5,
    "default_min_channel_width_percent": 1.0,
    "default_max_channel_width_percent": 6.0,
    "default_trade_cooldown_seconds": 60,
    "default_slope_lookback": 5,
    "default_max_sma_slope_percent": 0.15,
    "default_enable_slope_order_cancel": True,
    "default_force_close_at_opposite_band": True,
    "default_enable_channel_expansion_cancel": True,
    "default_channel_expansion_ratio": 2.0,
    "default_enable_stale_trade_close": True,
    "default_stale_trade_timeout_candles": 5,
    "default_enable_distance_cancel": True,
    "default_max_distance_from_trigger_percent": 2.0,
    "default_simulator_balance": 10000.0,
    "default_simulator_commission_percent": 0.055,
    "default_simulator_slippage_points": 2,
    "symbols_cache": [],
    "symbols_cache_updated_at": 0,
}


class SettingsManager:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.file_path = self.base_dir / SETTINGS_FILE
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if not self.file_path.exists():
            self._data = DEFAULT_SETTINGS.copy()
            self.save()
            return
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            merged = DEFAULT_SETTINGS.copy()
            merged.update(loaded)
            self._data = merged
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ Ошибка чтения {SETTINGS_FILE}: {e}. Использую дефолты.")
            self._data = DEFAULT_SETTINGS.copy()
            self.save()

    def save(self) -> None:
        tmp_path = self.file_path.with_suffix('.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.file_path)
        except OSError as e:
            print(f"❌ Ошибка сохранения настроек: {e}")

    def get(self, key: str, default=None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def update(self, data: Dict[str, Any]) -> None:
        self._data.update(data)
        self.save()

    @property
    def api_credentials(self) -> tuple:
        return self._data.get("api_key", ""), self._data.get("api_secret", "")

    def get_defaults_for_new_bot(self) -> Dict[str, Any]:
        """Возвращает ВСЕ параметры для подстановки в config_template.py"""
        return {
            "API_KEY": self._data.get("api_key", ""),
            "API_SECRET": self._data.get("api_secret", ""),
            "DEMO_TRADING": self._data.get("demo_trading", True),
            "RISK_PER_TRADE": self._data.get("default_risk_per_trade", 10.0),
            "BB_LENGTH": self._data.get("default_bb_length", 20),
            "BB_STD_DEV": self._data.get("default_bb_std_dev", 2.0),
            "ADAPTIVE_MODE": self._data.get("default_adaptive_mode", True),
            "TRAIL_PERCENT": self._data.get("default_trail_percent", 0.2),
            "SL_PERCENT": self._data.get("default_sl_percent", 0.6),
            "TP_PERCENT": self._data.get("default_tp_percent", 1.2),
            "BASE_TRAIL_PERCENT": self._data.get("default_base_trail_percent", 0.2),
            "TRAIL_GROWTH_FACTOR": self._data.get("default_trail_growth_factor", 0.15),
            "SL_FROM_TRAIL_PERCENT": self._data.get("default_sl_from_trail_percent", 120.0),
            "TP_FROM_WIDTH_PERCENT": self._data.get("default_tp_from_width_percent", 80.0),
            "MAKER_FEE_PERCENT": self._data.get("default_maker_fee_percent", 0.02),
            "TAKER_FEE_PERCENT": self._data.get("default_taker_fee_percent", 0.055),
            "RVOL_PERIOD": self._data.get("default_rvol_period", 20),
            "MAX_RVOL_FOR_REVERSAL": self._data.get("default_max_rvol_for_reversal", 500.0),
            "MIN_VOLATILITY_RATIO": self._data.get("default_min_volatility_ratio", 0.5),
            "MIN_CHANNEL_WIDTH_PERCENT": self._data.get("default_min_channel_width_percent", 1.0),
            "MAX_CHANNEL_WIDTH_PERCENT": self._data.get("default_max_channel_width_percent", 6.0),
            "TRADE_COOLDOWN_SECONDS": self._data.get("default_trade_cooldown_seconds", 60),
            "SLOPE_LOOKBACK": self._data.get("default_slope_lookback", 5),
            "MAX_SMA_SLOPE_PERCENT": self._data.get("default_max_sma_slope_percent", 0.15),
            "ENABLE_SLOPE_ORDER_CANCEL": self._data.get("default_enable_slope_order_cancel", True),
            "FORCE_CLOSE_AT_OPPOSITE_BAND": self._data.get("default_force_close_at_opposite_band", True),
            "ENABLE_CHANNEL_EXPANSION_CANCEL": self._data.get("default_enable_channel_expansion_cancel", True),
            "CHANNEL_EXPANSION_RATIO": self._data.get("default_channel_expansion_ratio", 2.0),
            "ENABLE_STALE_TRADE_CLOSE": self._data.get("default_enable_stale_trade_close", True),
            "STALE_TRADE_TIMEOUT_CANDLES": self._data.get("default_stale_trade_timeout_candles", 5),
            "ENABLE_DISTANCE_CANCEL": self._data.get("default_enable_distance_cancel", True),
            "MAX_DISTANCE_FROM_TRIGGER_PERCENT": self._data.get("default_max_distance_from_trigger_percent", 2.0),
            "SIMULATOR_BALANCE": self._data.get("default_simulator_balance", 10000.0),
            "SIMULATOR_COMMISSION_PERCENT": self._data.get("default_simulator_commission_percent", 0.055),
            "SIMULATOR_SLIPPAGE_POINTS": self._data.get("default_simulator_slippage_points", 2),
        }
