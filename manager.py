import sys
from pathlib import Path
from typing import Dict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QHeaderView,
    QMessageBox, QAbstractItemView, QDialog
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor

from core.settings import SettingsManager
from core.factory import BotFactory
from core.process import BotProcess
from core.symbols import SymbolLoader
from ui.create_dialog import CreateBotDialog
from ui.log_window import LogWindow
from ui.settings_dialog import SettingsDialog
from ui.config_dialog import ConfigEditDialog


class BotManagerApp(QMainWindow):
    """Главное окно менеджера ботов v1.0"""

    UPDATE_INTERVAL_MS = 1000  # Обновление таблицы раз в секунду

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bot Manager v1.0")
        self.setMinimumSize(1100, 650)

        # Инициализация ядра
        self.base_dir = Path(__file__).resolve().parent
        self.settings = SettingsManager(self.base_dir)
        self.factory = BotFactory(self.base_dir)
        self.symbol_loader = SymbolLoader(self.base_dir / "symbols_cache.json")

        # Активные процессы: {bot_name: BotProcess}
        self.processes: Dict[str, BotProcess] = {}

        # Кэш открытых окон логов
        self._log_windows: Dict[str, LogWindow] = {}

        self._setup_ui()
        self._load_bots()

        # Таймер обновления состояний (единственный таймер)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_table_states)
        self.update_timer.start(self.UPDATE_INTERVAL_MS)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # === Панель кнопок ===
        btn_layout = QHBoxLayout()

        self.btn_create = QPushButton("➕ Создать бота")
        self.btn_create.clicked.connect(self._on_create_bot)

        self.btn_start_all = QPushButton("▶ Запустить все")
        self.btn_start_all.clicked.connect(self._start_all_bots)

        self.btn_stop_all = QPushButton("⏹ Остановить все")
        self.btn_stop_all.clicked.connect(self._stop_all_bots)

        self.btn_refresh_symbols = QPushButton("🔄 Обновить монеты")
        self.btn_refresh_symbols.clicked.connect(self._refresh_symbols)

        self.btn_settings = QPushButton("⚙️ Настройки")
        self.btn_settings.clicked.connect(self._open_settings)

        self.lbl_status = QLabel("Готов")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        btn_layout.addWidget(self.btn_create)
        btn_layout.addWidget(self.btn_start_all)
        btn_layout.addWidget(self.btn_stop_all)
        btn_layout.addWidget(self.btn_refresh_symbols)
        btn_layout.addWidget(self.btn_settings)
        btn_layout.addStretch()
        btn_layout.addWidget(self.lbl_status)

        # === Таблица ботов ===
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Имя", "Символ", "ТФ", "Режим", "Статус",
            "PnL (сессия)", "Win Rate", "Uptime", "Действия"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(8, 140)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        layout.addLayout(btn_layout)
        layout.addWidget(self.table)

    def _load_bots(self):
        """Загружает список ботов из папки bots/ и создаёт для них BotProcess."""
        self.table.setRowCount(0)
        self.processes.clear()

        bots = self.factory.list_bots()
        for bot_info in bots:
            name = bot_info["name"]
            proc = BotProcess(
                bot_dir=bot_info["path"],
                symbol=bot_info["symbol"],
                timeframe=bot_info["timeframe"],
                mode=bot_info["mode"]
            )
            self.processes[name] = proc
            self._add_table_row(bot_info)

    def _add_table_row(self, bot_info: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(bot_info["name"]))
        self.table.setItem(row, 1, QTableWidgetItem(bot_info["symbol"]))
        self.table.setItem(row, 2, QTableWidgetItem(bot_info["timeframe"]))
        self.table.setItem(row, 3, QTableWidgetItem(bot_info["mode"].upper()))
        self.table.setItem(row, 4, QTableWidgetItem("⚪ Остановлен"))
        self.table.setItem(row, 5, QTableWidgetItem("0.00"))
        self.table.setItem(row, 6, QTableWidgetItem("-"))
        self.table.setItem(row, 7, QTableWidgetItem("-"))

        # Кнопки действий
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(4, 2, 4, 2)
        actions_layout.setSpacing(2)

        btn_toggle = QPushButton("▶")
        btn_toggle.setFixedWidth(30)
        btn_toggle.setToolTip("Запустить / Остановить")
        btn_toggle.clicked.connect(lambda _, n=bot_info["name"]: self._toggle_bot(n))

        btn_config = QPushButton("⚙️")
        btn_config.setFixedWidth(30)
        btn_config.setToolTip("Настройки бота")
        btn_config.clicked.connect(lambda _, n=bot_info["name"]: self._edit_bot_config(n))

        btn_logs = QPushButton("📄")
        btn_logs.setFixedWidth(30)
        btn_logs.setToolTip("Логи")
        btn_logs.clicked.connect(lambda _, n=bot_info["name"]: self._open_log_window(n))

        btn_delete = QPushButton("🗑")
        btn_delete.setFixedWidth(30)
        btn_delete.setToolTip("Удалить бота")
        btn_delete.clicked.connect(lambda _, n=bot_info["name"]: self._delete_bot(n))

        actions_layout.addWidget(btn_toggle)
        actions_layout.addWidget(btn_config)
        actions_layout.addWidget(btn_logs)
        actions_layout.addWidget(btn_delete)

        self.table.setCellWidget(row, 8, actions_widget)

    def _update_table_states(self):
        """Обновляет статусы, PnL, Win Rate и Uptime для всех ботов."""
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if not name_item:
                continue
            name = name_item.text()
            proc = self.processes.get(name)
            if not proc:
                continue

            state = proc.get_state()

            # Статус с цветовой индикацией
            status_item = self.table.item(row, 4)
            if status_item:
                status_text = state["status"]
                status_item.setText(status_text)
                color_map = {
                    "🟢 Мониторинг": QColor(200, 255, 200),
                    "🟡 Отложенный ордер": QColor(255, 255, 180),
                    "🔵 В позиции": QColor(180, 220, 255),
                    "🔴 Ошибка": QColor(255, 200, 200),
                    "⚪ Остановлен": QColor(240, 240, 240),
                }
                bg = color_map.get(status_text)
                if bg:
                    status_item.setBackground(bg)

            # PnL
            pnl_item = self.table.item(row, 5)
            if pnl_item:
                pnl_val = state.get("session_pnl", 0.0)
                pnl_item.setText(f"{pnl_val:+.2f}")
                if pnl_val > 0:
                    pnl_item.setForeground(QColor(0, 150, 0))
                elif pnl_val < 0:
                    pnl_item.setForeground(QColor(200, 0, 0))
                else:
                    pnl_item.setForeground(QColor(0, 0, 0))

            # Win Rate
            wr_item = self.table.item(row, 6)
            if wr_item:
                total = state.get("total_trades", 0)
                if total > 0:
                    wr_item.setText(f"{state['win_rate']:.1f}% ({total})")
                else:
                    wr_item.setText("-")

            # Uptime
            uptime_item = self.table.item(row, 7)
            if uptime_item:
                if state["is_running"]:
                    secs = int(state.get("uptime", 0))
                    m, s = divmod(secs, 60)
                    h, m = divmod(m, 60)
                    uptime_item.setText(f"{h:02d}:{m:02d}:{s:02d}")
                else:
                    uptime_item.setText("-")

            # Обновляем текст кнопки запуска/остановки
            actions_widget = self.table.cellWidget(row, 8)
            if actions_widget:
                btns = actions_widget.findChildren(QPushButton)
                if btns:
                    btns[0].setText("⏹" if state["is_running"] else "▶")

    # === Действия ===

    def _toggle_bot(self, bot_name: str):
        proc = self.processes.get(bot_name)
        if not proc:
            return
        if proc.is_running:
            proc.stop()
        else:
            if not proc.start():
                QMessageBox.critical(self, "Ошибка запуска",
                                     f"Не удалось запустить бота '{bot_name}'.\nПроверьте startup_error.log")

    def _start_all_bots(self):
        for proc in self.processes.values():
            if not proc.is_running:
                proc.start()

    def _stop_all_bots(self):
        for proc in self.processes.values():
            if proc.is_running:
                proc.stop()

    def _delete_bot(self, bot_name: str):
        reply = QMessageBox.question(
            self, "Удаление бота",
            f"Удалить бота '{bot_name}' и все его файлы?\nЭто действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Закрываем окно логов если открыто
            if bot_name in self._log_windows:
                self._log_windows[bot_name].close()
                del self._log_windows[bot_name]

            proc = self.processes.get(bot_name)
            if proc:
                proc.delete()
                del self.processes[bot_name]
            self._load_bots()

    def _open_log_window(self, bot_name: str):
        # Не создаём дубликат окна
        if bot_name in self._log_windows and self._log_windows[bot_name].isVisible():
            self._log_windows[bot_name].raise_()
            self._log_windows[bot_name].activateWindow()
            return

        proc = self.processes.get(bot_name)
        if not proc:
            QMessageBox.warning(self, "Ошибка", f"Бот '{bot_name}' не найден.")
            return

        window = LogWindow(proc, self)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.destroyed.connect(lambda: self._log_windows.pop(bot_name, None))
        self._log_windows[bot_name] = window
        window.show()

    def _edit_bot_config(self, bot_name: str):
        proc = self.processes.get(bot_name)
        if not proc:
            QMessageBox.warning(self, "Ошибка", f"Бот '{bot_name}' не найден.")
            return

        was_running = proc.is_running
        if was_running:
            reply = QMessageBox.question(
                self, "Редактирование конфига",
                f"Бот '{bot_name}' сейчас работает.\n"
                "Изменения применятся только после перезапуска.\n\n"
                "Остановить бота перед редактированием?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                proc.stop()

        dialog = ConfigEditDialog(proc.bot_dir, bot_name, self)
        dialog.exec()

    def _on_create_bot(self):
        dialog = CreateBotDialog(self.factory, self.symbol_loader, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_bots()

    def _open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.exec()

    def _refresh_symbols(self):
        self.lbl_status.setText("⏳ Загрузка монет...")
        self.btn_refresh_symbols.setEnabled(False)
        QApplication.processEvents()

        symbols = self.symbol_loader.fetch_from_api()

        self.lbl_status.setText(f"✅ Загружено {len(symbols)} монет")
        self.btn_refresh_symbols.setEnabled(True)

    def closeEvent(self, event):
        """Корректная остановка всех ботов при закрытии окна."""
        reply = QMessageBox.question(
            self, "Выход",
            "Остановить всех работающих ботов перед выходом?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )

        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return

        if reply == QMessageBox.StandardButton.Yes:
            for proc in self.processes.values():
                proc.stop()

        # Закрываем все окна логов
        for window in list(self._log_windows.values()):
            window.close()

        event.accept()


def main():
    app = QApplication(sys.argv)

    # Глобальный стиль для консистентности на Windows и Linux
    app.setStyle("Fusion")

    window = BotManagerApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
