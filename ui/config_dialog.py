import re
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QCheckBox, QPushButton, QHBoxLayout, QLabel, QMessageBox,
    QGroupBox, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt


class BotConfigEditor:
    """
    Читает и пишет config.py бота через regex-парсинг.
    Не импортирует конфиг как модуль (безопасно).
    """

    EDITABLE_FIELDS = {
        "RISK_PER_TRADE": ("Риск на сделку (%)", float, 0.1, 100.0, 2),
        "BB_LENGTH": ("BB Length", int, 5, 200, 0),
        "BB_STD_DEV": ("BB Std Dev", float, 0.5, 5.0, 2),
        "ADAPTIVE_MODE": ("Адаптивный режим", bool, None, None, None),
        "TRAIL_PERCENT": ("Trail % (фикс.)", float, 0.01, 10.0, 3),
        "SL_PERCENT": ("SL % (фикс.)", float, 0.01, 20.0, 3),
        "TP_PERCENT": ("TP % (фикс.)", float, 0.01, 20.0, 3),
        "BASE_TRAIL_PERCENT": ("Base Trail % (адапт.)", float, 0.01, 10.0, 3),
        "TRAIL_GROWTH_FACTOR": ("Trail Growth Factor", float, 0.0, 5.0, 3),
        "SL_FROM_TRAIL_PERCENT": ("SL from Trail %", float, 10.0, 500.0, 1),
        "TP_FROM_WIDTH_PERCENT": ("TP from Width %", float, 10.0, 500.0, 1),
        "MAKER_FEE_PERCENT": ("Maker Fee %", float, 0.0, 1.0, 4),
        "TAKER_FEE_PERCENT": ("Taker Fee %", float, 0.0, 1.0, 4),
        "RVOL_PERIOD": ("RVOL Period", int, 5, 100, 0),
        "MAX_RVOL_FOR_REVERSAL": ("Max RVOL", float, 1.0, 1000.0, 1),
        "MIN_VOLATILITY_RATIO": ("Min Volatility Ratio", float, 0.1, 10.0, 2),
        "MIN_CHANNEL_WIDTH_PERCENT": ("Min Channel Width %", float, 0.1, 20.0, 2),
        "MAX_CHANNEL_WIDTH_PERCENT": ("Max Channel Width %", float, 0.1, 50.0, 2),
        "TRADE_COOLDOWN_SECONDS": ("Cooldown (сек)", int, 0, 600, 0),
        "SLOPE_LOOKBACK": ("Slope Lookback", int, 1, 50, 0),
        "MAX_SMA_SLOPE_PERCENT": ("Max SMA Slope %", float, 0.01, 5.0, 3),
        "ENABLE_SLOPE_ORDER_CANCEL": ("Отмена по Slope", bool, None, None, None),
        "FORCE_CLOSE_AT_OPPOSITE_BAND": ("Force Close at Band", bool, None, None, None),
        "ENABLE_CHANNEL_EXPANSION_CANCEL": ("Отмена по расширению", bool, None, None, None),
        "CHANNEL_EXPANSION_RATIO": ("Channel Expansion Ratio", float, 1.0, 10.0, 2),
        "ENABLE_STALE_TRADE_CLOSE": ("Закрытие по застою", bool, None, None, None),
        "STALE_TRADE_TIMEOUT_CANDLES": ("Timeout свечей", int, 1, 100, 0),
        "ENABLE_DISTANCE_CANCEL": ("Отмена по дистанции", bool, None, None, None),
        "MAX_DISTANCE_FROM_TRIGGER_PERCENT": ("Max Distance %", float, 0.1, 20.0, 2),
        "SIMULATOR_BALANCE": ("Баланс симулятора", float, 100, 1000000, 2),
        "SIMULATOR_COMMISSION_PERCENT": ("Комиссия симулятора %", float, 0.0, 1.0, 4),
    }

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._content: str = ""
        self._values: dict = {}

    def load(self) -> bool:
        try:
            self._content = self.config_path.read_text(encoding="utf-8")
            for key in self.EDITABLE_FIELDS:
                pattern = rf'^{key}\s*=\s*(.+)$'
                match = re.search(pattern, self._content, re.MULTILINE)
                if match:
                    raw = match.group(1).strip()
                    field_type = self.EDITABLE_FIELDS[key][1]
                    if field_type == bool:
                        self._values[key] = raw.lower() == "true"
                    elif field_type == int:
                        self._values[key] = int(float(raw))
                    else:
                        self._values[key] = float(raw)
            return True
        except Exception as e:
            print(f"❌ Ошибка чтения конфига: {e}")
            return False

    def get_value(self, key: str):
        return self._values.get(key)

    def save(self, new_values: dict) -> bool:
        try:
            content = self._content
            for key, value in new_values.items():
                if key not in self.EDITABLE_FIELDS:
                    continue
                field_type = self.EDITABLE_FIELDS[key][1]
                if field_type == bool:
                    replacement = "True" if value else "False"
                elif field_type == int:
                    replacement = str(int(value))
                else:
                    replacement = str(round(float(value), 6))
                pattern = rf'^({key}\s*=\s*).+$'
                content = re.sub(pattern, rf'\g<1>{replacement}', content, flags=re.MULTILINE)
            self.config_path.write_text(content, encoding="utf-8")
            self._content = content
            self._values.update(new_values)
            return True
        except Exception as e:
            print(f"❌ Ошибка сохранения конфига: {e}")
            return False


class ConfigEditDialog(QDialog):
    """Диалог редактирования конфига конкретного бота."""

    def __init__(self, bot_dir: Path, bot_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Настройки: {bot_name}")
        self.setMinimumSize(600, 750)
        self.setModal(True)
        self.editor = BotConfigEditor(bot_dir / "config.py")
        self._widgets: dict = {}
        if not self.editor.load():
            QMessageBox.critical(self, "Ошибка", "Не удалось прочитать config.py")
            self.reject()
            return
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        lbl_info = QLabel("⚠️ Изменения применятся после перезапуска бота.")
        lbl_info.setStyleSheet("color: #b8860b; font-style: italic;")
        lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        form = QFormLayout(scroll_widget)

        groups = {
            "Размер позиции": ["RISK_PER_TRADE"],
            "Bollinger Bands": ["BB_LENGTH", "BB_STD_DEV"],
            "Режим трейлинга": ["ADAPTIVE_MODE"],
            "Фиксированные параметры": ["TRAIL_PERCENT", "SL_PERCENT", "TP_PERCENT"],
            "Адаптивные параметры": [
                "BASE_TRAIL_PERCENT", "TRAIL_GROWTH_FACTOR",
                "SL_FROM_TRAIL_PERCENT", "TP_FROM_WIDTH_PERCENT"
            ],
            "Комиссии": ["MAKER_FEE_PERCENT", "TAKER_FEE_PERCENT"],
            "Фильтры входа": [
                "RVOL_PERIOD", "MAX_RVOL_FOR_REVERSAL",
                "MIN_VOLATILITY_RATIO",
                "MIN_CHANNEL_WIDTH_PERCENT", "MAX_CHANNEL_WIDTH_PERCENT",
                "TRADE_COOLDOWN_SECONDS"
            ],
            "SMA Slope фильтр": [
                "SLOPE_LOOKBACK", "MAX_SMA_SLOPE_PERCENT", "ENABLE_SLOPE_ORDER_CANCEL"
            ],
            "Принудительное закрытие": [
                "FORCE_CLOSE_AT_OPPOSITE_BAND",
                "ENABLE_CHANNEL_EXPANSION_CANCEL", "CHANNEL_EXPANSION_RATIO",
                "ENABLE_STALE_TRADE_CLOSE", "STALE_TRADE_TIMEOUT_CANDLES",
                "ENABLE_DISTANCE_CANCEL", "MAX_DISTANCE_FROM_TRIGGER_PERCENT"
            ],
            "Симулятор": ["SIMULATOR_BALANCE", "SIMULATOR_COMMISSION_PERCENT"],
        }

        for group_name, fields in groups.items():
            group_box = QGroupBox(group_name)
            group_layout = QFormLayout(group_box)
            for key in fields:
                if key not in BotConfigEditor.EDITABLE_FIELDS:
                    continue
                label_text, field_type, min_val, max_val, decimals = BotConfigEditor.EDITABLE_FIELDS[key]
                if field_type == bool:
                    widget = QCheckBox()
                elif field_type == int:
                    widget = QDoubleSpinBox()
                    widget.setRange(min_val, max_val)
                    widget.setDecimals(0)
                else:
                    widget = QDoubleSpinBox()
                    widget.setRange(min_val, max_val)
                    widget.setDecimals(decimals)
                    widget.setSingleStep(0.01 if decimals >= 2 else 0.1)
                group_layout.addRow(f"{label_text}:", widget)
                self._widgets[key] = widget
            form.addRow(group_box)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_save = QPushButton("💾 Сохранить")
        btn_save.clicked.connect(self._on_save)
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def _load_values(self):
        for key, widget in self._widgets.items():
            value = self.editor.get_value(key)
            if value is None:
                continue
            field_type = BotConfigEditor.EDITABLE_FIELDS[key][1]
            if field_type == bool:
                widget.setChecked(value)
            else:
                widget.setValue(value)

    def _on_save(self):
        new_values = {}
        for key, widget in self._widgets.items():
            field_type = BotConfigEditor.EDITABLE_FIELDS[key][1]
            if field_type == bool:
                new_values[key] = widget.isChecked()
            else:
                new_values[key] = widget.value()
        if self.editor.save(new_values):
            QMessageBox.information(self, "Успех", "Конфигурация сохранена.\nПерезапустите бота для применения.")
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить конфигурацию.")
