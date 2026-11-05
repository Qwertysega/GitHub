import time
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QTabWidget, QLabel
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat

from core.process import BotProcess


class LogWindow(QDialog):
    """
    Окно логов бота.
    Обе вкладки читают файлы напрямую из папки бота.
    Менеджер НЕ владеет файлами — только читает.
    """

    REFRESH_INTERVAL_MS = 500   # Обновление каждые 500мс для отзывчивости
    MAX_LINES = 1000

    def __init__(self, bot_process: BotProcess, parent=None):
        super().__init__(parent)
        self.bot = bot_process
        self.setWindowTitle(f"Логи: {bot_process.symbol} ({bot_process.timeframe}) [{bot_process.mode.upper()}]")
        self.setMinimumSize(900, 650)
        self.setModal(False)

        # Позиции tailer для обоих файлов
        self._trade_pos: int = 0
        self._trade_size: int = 0
        self._sys_pos: int = 0
        self._sys_size: int = 0

        self._setup_ui()
        self._load_tails()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_logs)
        self.timer.start(self.REFRESH_INTERVAL_MS)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.lbl_status = QLabel("⚪ Остановлен")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(self.lbl_status)

        self.tabs = QTabWidget()

        self.trade_text = QTextEdit()
        self.trade_text.setReadOnly(True)
        self.trade_text.setFont(QFont("Consolas", 9))
        self.trade_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.trade_text, "📈 Торговый лог")

        self.sys_text = QTextEdit()
        self.sys_text.setReadOnly(True)
        self.sys_text.setFont(QFont("Consolas", 9))
        self.sys_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.sys_text, "📋 Системный лог")

        layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        btn_clear_trade = QPushButton("Очистить торговый")
        btn_clear_trade.clicked.connect(lambda: self.trade_text.clear())
        btn_clear_sys = QPushButton("Очистить системный")
        btn_clear_sys.clicked.connect(lambda: self.sys_text.clear())
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.close)

        btn_layout.addWidget(btn_clear_trade)
        btn_layout.addWidget(btn_clear_sys)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def _load_tails(self):
        """Загружает хвосты обоих файлов при открытии окна."""
        self._trade_pos, self._trade_size = self._load_tail(
            self.bot.log_file, self.trade_text, self._colorize_trade_line
        )
        self._sys_pos, self._sys_size = self._load_tail(
            self.bot.error_log_file, self.sys_text, self._colorize_sys_line
        )

    def _load_tail(self, filepath, text_widget, colorize_func):
        try:
            if not filepath.exists():
                return 0, 0
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                tail = lines[-100:] if len(lines) > 100 else lines
                for line in tail:
                    colorize_func(text_widget, line.rstrip())
                pos = f.tell()
                size = filepath.stat().st_size
                return pos, size
        except Exception:
            return 0, 0

    def _update_logs(self):
        """Основной цикл обновления обеих вкладок."""
        state = self.bot.get_state()
        self.lbl_status.setText(state["status"])

        self._read_file(self.bot.log_file, self.trade_text, self._colorize_trade_line,
                        '_trade_pos', '_trade_size')
        self._read_file(self.bot.error_log_file, self.sys_text, self._colorize_sys_line,
                        '_sys_pos', '_sys_size')

    def _read_file(self, filepath, text_widget, colorize_func, pos_attr, size_attr):
        try:
            if not filepath.exists():
                return

            current_size = filepath.stat().st_size
            pos = getattr(self, pos_attr)
            last_size = getattr(self, size_attr)

            # Файл пересоздан или очищен externally
            if current_size < last_size:
                pos = 0
                text_widget.clear()

            setattr(self, size_attr, current_size)

            if pos >= current_size:
                return

            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(pos)
                new_data = f.read()
                new_pos = f.tell()

            setattr(self, pos_attr, new_pos)

            if new_data.strip():
                for line in new_data.strip().split('\n'):
                    colorize_func(text_widget, line)

        except PermissionError:
            pass
        except Exception:
            pass

    # === Подсветка торгового лога ===
    def _colorize_trade_line(self, widget: QTextEdit, line: str):
        color = None
        if "🟢 ОТКРЫТИЕ" in line or "🟢 МОНИТОРИНГ" in line:
            color = QColor(0, 150, 0)
        elif "⚡ ИСПОЛНЕНИЕ" in line:
            color = QColor(0, 100, 200)
        elif "🔴 ЗАКРЫТИЕ" in line:
            if "PnL:" in line:
                pnl_part = line.split("PnL:")[1].split("|")[0] if "|" in line else ""
                color = QColor(0, 180, 0) if "+" in pnl_part else QColor(200, 50, 50)
            else:
                color = QColor(200, 50, 50)
        elif "⚪ ОТМЕНА" in line:
            color = QColor(180, 140, 0)
        elif "⚡ ПРИНУДИТЕЛЬНОЕ" in line:
            color = QColor(200, 100, 0)
        self._append_colored(widget, line, color)

    # === Подсветка системного лога ===
    def _colorize_sys_line(self, widget: QTextEdit, line: str):
        color = None
        if " - ERROR - " in line or " - CRITICAL - " in line or "Traceback" in line:
            color = QColor(220, 50, 50)
        elif " - WARNING - " in line or "⚠️" in line:
            color = QColor(200, 160, 0)
        elif "🏃 Трейлинг" in line:
            color = QColor(80, 160, 220)
        elif "Connected" in line or "✅" in line:
            color = QColor(50, 180, 50)
        elif "Пропуск" in line or "Запрет" in line:
            color = QColor(180, 140, 0)
        elif "Force Close" in line or "ПРИНУДИТЕЛЬНОЕ" in line:
            color = QColor(220, 100, 0)
        elif "запущен" in line or "МОНИТОРИНГ" in line:
            color = QColor(100, 180, 100)
        self._append_colored(widget, line, color)

    # === Универсальный метод добавления строки ===
    def _append_colored(self, widget: QTextEdit, line: str, color: QColor = None):
        cursor = widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if color:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.insertText(line + "\n", fmt)
        else:
            cursor.insertText(line + "\n")

        if widget.document().blockCount() > self.MAX_LINES:
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

        scrollbar = widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()
