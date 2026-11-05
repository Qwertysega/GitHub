from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QCheckBox, QPushButton, QHBoxLayout, QLabel, QMessageBox,
    QGroupBox, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt
from core.settings import SettingsManager


class SettingsDialog(QDialog):
    """Диалог глобальных настроек менеджера."""

    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Глобальные настройки")
        self.setMinimumSize(600, 750)
        self.setModal(True)
        self.settings = settings
        self._widgets = {}
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # === API Ключи ===
        api_group = QGroupBox("Bybit API")
        api_layout = QFormLayout(api_group)
        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_api_key.setPlaceholderText("API Key")
        self.edit_api_secret = QLineEdit()
        self.edit_api_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_api_secret.setPlaceholderText("API Secret")
        api_layout.addRow("API Key:", self.edit_api_key)
        api_layout.addRow("API Secret:", self.edit_api_secret)
        self.chk_demo_trading = QCheckBox("Демо-торговля (ключи из кабинета «Демо-трейдинг» Bybit)")
        api_layout.addRow(self.chk_demo_trading)
        lbl_demo_hint = QLabel(
            "Демо-ключи работают только с api-demo.bybit.com, обычные — только с api.bybit.com. "
            "Несовпадение даёт ошибку 401."
        )
        lbl_demo_hint.setWordWrap(True)
        lbl_demo_hint.setStyleSheet("color: #888; font-style: italic;")
        api_layout.addRow(lbl_demo_hint)

        # Scroll area для всех дефолтов
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        defaults_form = QFormLayout(scroll_widget)

        groups = {
            "Размер позиции": [
                ("risk_per_trade", "Риск на сделку (%)", float, 0.1, 100.0, 2),
            ],
            "Bollinger Bands": [
                ("bb_length", "BB Length", int, 5, 200, 0),
                ("bb_std_dev", "BB Std Dev", float, 0.5, 5.0, 2),
            ],
            "Режим трейлинга": [
                ("adaptive_mode", "Адаптивный режим", bool, None, None, None),
            ],
            "Фиксированные параметры": [
                ("trail_percent", "Trail % (фикс.)", float, 0.01, 10.0, 3),
                ("sl_percent", "SL % (фикс.)", float, 0.01, 20.0, 3),
                ("tp_percent", "TP % (фикс.)", float, 0.01, 20.0, 3),
            ],
            "Адаптивные параметры": [
                ("base_trail_percent", "Base Trail %", float, 0.01, 10.0, 3),
                ("trail_growth_factor", "Trail Growth Factor", float, 0.0, 5.0, 3),
                ("sl_from_trail_percent", "SL from Trail %", float, 10.0, 500.0, 1),
                ("tp_from_width_percent", "TP from Width %", float, 10.0, 500.0, 1),
            ],
            "Комиссии": [
                ("maker_fee_percent", "Maker Fee %", float, 0.0, 1.0, 4),
                ("taker_fee_percent", "Taker Fee %", float, 0.0, 1.0, 4),
            ],
            "Фильтры входа": [
                ("rvol_period", "RVOL Period", int, 5, 100, 0),
                ("max_rvol_for_reversal", "Max RVOL", float, 1.0, 1000.0, 1),
                ("min_volatility_ratio", "Min Volatility Ratio", float, 0.1, 10.0, 2),
                ("min_channel_width_percent", "Min Channel Width %", float, 0.1, 20.0, 2),
                ("max_channel_width_percent", "Max Channel Width %", float, 0.1, 50.0, 2),
                ("trade_cooldown_seconds", "Cooldown (сек)", int, 0, 600, 0),
            ],
            "SMA Slope фильтр": [
                ("slope_lookback", "Slope Lookback", int, 1, 50, 0),
                ("max_sma_slope_percent", "Max SMA Slope %", float, 0.01, 5.0, 3),
                ("enable_slope_order_cancel", "Отмена по Slope", bool, None, None, None),
            ],
            "Принудительное закрытие": [
                ("force_close_at_opposite_band", "Force Close at Band", bool, None, None, None),
                ("enable_channel_expansion_cancel", "Отмена по расширению", bool, None, None, None),
                ("channel_expansion_ratio", "Channel Expansion Ratio", float, 1.0, 10.0, 2),
                ("enable_stale_trade_close", "Закрытие по застою", bool, None, None, None),
                ("stale_trade_timeout_candles", "Timeout свечей", int, 1, 100, 0),
                ("enable_distance_cancel", "Отмена по дистанции", bool, None, None, None),
                ("max_distance_from_trigger_percent", "Max Distance %", float, 0.1, 20.0, 2),
            ],
            "Симулятор": [
                ("simulator_balance", "Баланс симулятора", float, 100, 1000000, 2),
                ("simulator_commission_percent", "Комиссия симулятора %", float, 0.0, 1.0, 4),
                ("simulator_slippage_points", "Слиппедж (пунктов)", int, 0, 1000, 0),
            ],
        }

        for group_name, fields in groups.items():
            group_box = QGroupBox(group_name)
            group_layout = QFormLayout(group_box)
            for param_key, label_text, field_type, min_val, max_val, decimals in fields:
                storage_key = f"default_{param_key}"
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
                self._widgets[storage_key] = (widget, field_type)
            defaults_form.addRow(group_box)

        scroll.setWidget(scroll_widget)

        # === Кнопки ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_save = QPushButton("💾 Сохранить")
        btn_save.clicked.connect(self._on_save)
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)

        lbl_warning = QLabel("⚠️ Изменения применятся только к НОВЫМ ботам.")
        lbl_warning.setStyleSheet("color: #b8860b; font-style: italic;")
        lbl_warning.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(api_group)
        layout.addWidget(scroll)
        layout.addWidget(lbl_warning)
        layout.addLayout(btn_layout)

    def _load_values(self):
        self.edit_api_key.setText(self.settings.get("api_key", ""))
        self.edit_api_secret.setText(self.settings.get("api_secret", ""))
        self.chk_demo_trading.setChecked(bool(self.settings.get("demo_trading", True)))
        for storage_key, (widget, field_type) in self._widgets.items():
            value = self.settings.get(storage_key)
            if value is None:
                continue
            if field_type == bool:
                widget.setChecked(bool(value))
            else:
                widget.setValue(float(value))

    def _on_save(self):
        api_key = self.edit_api_key.text().strip()
        api_secret = self.edit_api_secret.text().strip()
        if not api_key or not api_secret:
            QMessageBox.warning(self, "Внимание", "API ключи не могут быть пустыми!")
            return

        update_data = {
            "api_key": api_key,
            "api_secret": api_secret,
            "demo_trading": self.chk_demo_trading.isChecked(),
        }
        for storage_key, (widget, field_type) in self._widgets.items():
            if field_type == bool:
                update_data[storage_key] = widget.isChecked()
            elif field_type == int:
                update_data[storage_key] = int(widget.value())
            else:
                update_data[storage_key] = widget.value()

        self.settings.update(update_data)
        QMessageBox.information(self, "Успех", "Глобальные настройки сохранены.")
        self.accept()
