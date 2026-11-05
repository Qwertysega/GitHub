from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QListWidget, QListWidgetItem,
    QMessageBox, QGroupBox, QFormLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from typing import List, Dict, Optional

from core.symbols import SymbolLoader
from core.factory import BotFactory


class SymbolLoadWorker(QThread):
    """Фоновая загрузка символов, чтобы не морозить GUI."""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, loader: SymbolLoader, force_refresh: bool = False):
        super().__init__()
        self.loader = loader
        self.force_refresh = force_refresh

    def run(self):
        try:
            symbols = self.loader.get_symbols(force_refresh=self.force_refresh)
            self.finished.emit(symbols)
        except Exception as e:
            self.error.emit(str(e))


class CreateBotDialog(QDialog):
    """Диалог создания нового бота."""

    TIMEFRAMES = ["1", "3", "5", "15", "30", "60", "120", "240", "D"]
    MODES = [("sim", "🎮 Симулятор"), ("live", "🌐 Реальная торговля")]

    def __init__(self, factory: BotFactory, symbol_loader: SymbolLoader, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать нового бота")
        self.setMinimumWidth(450)
        self.setModal(True)

        self.factory = factory
        self.symbol_loader = symbol_loader
        self._all_symbols: List[Dict[str, str]] = []
        self._worker: Optional[SymbolLoadWorker] = None

        self._setup_ui()
        self._load_symbols()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # === Поиск монеты ===
        search_group = QGroupBox("Монета")
        search_layout = QVBoxLayout(search_group)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск: BTC, ETH, SOL...")
        self.search_input.textChanged.connect(self._on_search_changed)

        self.symbol_list = QListWidget()
        self.symbol_list.setMaximumHeight(200)
        self.symbol_list.currentItemChanged.connect(self._on_symbol_selected)

        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.symbol_list)

        # === Параметры ===
        params_group = QGroupBox("Параметры")
        params_layout = QFormLayout(params_group)

        self.lbl_selected = QLabel("Не выбрано")
        self.lbl_selected.setStyleSheet("font-weight: bold; color: #555;")

        self.combo_tf = QComboBox()
        self.combo_tf.addItems(self.TIMEFRAMES)
        self.combo_tf.setCurrentText("5")

        self.combo_mode = QComboBox()
        for value, label in self.MODES:
            self.combo_mode.addItem(label, value)

        params_layout.addRow("Выбрано:", self.lbl_selected)
        params_layout.addRow("Таймфрейм:", self.combo_tf)
        params_layout.addRow("Режим:", self.combo_mode)

        # === Кнопки ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_create = QPushButton("✅ Создать")
        self.btn_create.setEnabled(False)
        self.btn_create.clicked.connect(self._on_create)

        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_create)

        # Статус загрузки
        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(search_group)
        layout.addWidget(params_group)
        layout.addWidget(self.lbl_status)
        layout.addLayout(btn_layout)

    def _load_symbols(self, force_refresh: bool = False):
        self.lbl_status.setText("⏳ Загрузка монет...")
        self.search_input.setEnabled(False)
        self.symbol_list.setEnabled(False)

        self._worker = SymbolLoadWorker(self.symbol_loader, force_refresh)
        self._worker.finished.connect(self._on_symbols_loaded)
        self._worker.error.connect(self._on_symbols_error)
        self._worker.start()

    def _on_symbols_loaded(self, symbols: list):
        self._all_symbols = symbols
        self._populate_symbol_list(symbols[:50])  # Показываем первые 50
        self.lbl_status.setText(f"✅ Загружено {len(symbols)} монет")
        self.search_input.setEnabled(True)
        self.symbol_list.setEnabled(True)

    def _on_symbols_error(self, error_msg: str):
        self.lbl_status.setText(f"❌ Ошибка: {error_msg}")
        self.search_input.setEnabled(True)
        self.symbol_list.setEnabled(True)

    def _populate_symbol_list(self, symbols: list):
        self.symbol_list.clear()
        for s in symbols:
            item = QListWidgetItem(f"{s['symbol']}  ({s['baseCoin']}/{s['quoteCoin']})")
            item.setData(Qt.ItemDataRole.UserRole, s["symbol"])
            self.symbol_list.addItem(item)

    def _on_search_changed(self, text: str):
        results = self.symbol_loader.search(text, limit=50)
        self._populate_symbol_list(results)

    def _on_symbol_selected(self, current: QListWidgetItem, previous):
        if current:
            symbol = current.data(Qt.ItemDataRole.UserRole)
            self.lbl_selected.setText(symbol)
            self.lbl_selected.setStyleSheet("font-weight: bold; color: #0078d4;")
            self.btn_create.setEnabled(True)
        else:
            self.lbl_selected.setText("Не выбрано")
            self.lbl_selected.setStyleSheet("font-weight: bold; color: #555;")
            self.btn_create.setEnabled(False)

    def _on_create(self):
        current_item = self.symbol_list.currentItem()
        if not current_item:
            return

        symbol = current_item.data(Qt.ItemDataRole.UserRole)
        timeframe = self.combo_tf.currentText()
        mode = self.combo_mode.currentData()

        # Создаём бота через фабрику
        bot_dir = self.factory.create_bot(symbol=symbol, timeframe=timeframe, mode=mode)

        if bot_dir:
            QMessageBox.information(self, "Успех", f"Бот создан:\n{bot_dir.name}")
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось создать бота. Проверьте консоль.")

    def closeEvent(self, event):
        """Корректная остановка worker при закрытии."""
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        event.accept()
