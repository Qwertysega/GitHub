import re
import time
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Any


class BotStatus(Enum):
    MONITORING = "🟢 Мониторинг"
    PENDING = "🟡 Отложенный ордер"
    IN_POSITION = "🔵 В позиции"
    ERROR = "🔴 Ошибка"
    STOPPED = "⚪ Остановлен"


class LogParser:
    """Инкрементальный парсер торгового лога бота v33.0."""

    RE_MONITORING = re.compile(r'🟢 МОНИТОРИНГ')
    RE_OPEN = re.compile(r'🟢 ОТКРЫТИЕ (BUY|SELL)')
    RE_EXECUTE = re.compile(r'⚡ ИСПОЛНЕНИЕ (BUY|SELL)')
    RE_CLOSE = re.compile(
        r'🔴 ЗАКРЫТИЕ .+ PnL: ([+-]?\d+\.\d+) USDT \| Баланс: (\d+\.\d+)'
    )
    RE_CANCEL = re.compile(r'⚪ ОТМЕНА')
    RE_FORCE_CLOSE_MARKER = re.compile(r'⚡ ПРИНУДИТЕЛЬНОЕ ЗАКРЫТИЕ')

    TAIL_LINES_ON_INIT = 150

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self._position: int = 0
        self._last_size: int = 0
        self._initialized: bool = False

        self.status: BotStatus = BotStatus.STOPPED
        self.session_pnl: float = 0.0
        self.total_trades: int = 0
        self.wins: int = 0
        self.losses: int = 0
        self.last_balance: float = 0.0
        self.last_update_time: float = 0.0
        self.order_side: Optional[str] = None
        self._expecting_close_pnl: bool = False

    def _read_tail(self, lines_count: int) -> list:
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                return all_lines[-lines_count:] if len(all_lines) > lines_count else all_lines
        except (FileNotFoundError, PermissionError):
            return []

    def _read_new_lines(self) -> list:
        try:
            current_size = self.log_file.stat().st_size
        except (FileNotFoundError, OSError):
            return []

        if current_size < self._last_size:
            self._position = 0

        self._last_size = current_size

        if self._position >= current_size:
            return []

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(self._position)
                new_data = f.read()
                self._position = f.tell()
                return new_data.strip().split('\n') if new_data.strip() else []
        except PermissionError:
            return []

    def _process_line(self, line: str) -> None:
        if not line:
            return

        self.last_update_time = time.time()

        # 0. Маркер запуска → MONITORING
        if self.RE_MONITORING.search(line):
            self.status = BotStatus.MONITORING
            return

        # 1. Открытие ордера → PENDING
        m = self.RE_OPEN.search(line)
        if m:
            self.status = BotStatus.PENDING
            self.order_side = m.group(1)
            self._expecting_close_pnl = False
            return

        # 2. Исполнение → IN_POSITION
        m = self.RE_EXECUTE.search(line)
        if m:
            self.status = BotStatus.IN_POSITION
            self.order_side = m.group(1)
            self._expecting_close_pnl = False
            return

        # 3. Закрытие позиции → MONITORING + PnL
        m = self.RE_CLOSE.search(line)
        if m:
            pnl = float(m.group(1))
            balance = float(m.group(2))
            self.session_pnl += pnl
            self.total_trades += 1
            self.last_balance = balance
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            self.status = BotStatus.MONITORING
            self.order_side = None
            self._expecting_close_pnl = False
            return

        # 4. Маркер принудительного закрытия
        if self.RE_FORCE_CLOSE_MARKER.search(line):
            self._expecting_close_pnl = True
            return

        # 5. Отмена ордера → MONITORING
        if self.RE_CANCEL.search(line):
            if self.status == BotStatus.PENDING:
                self.status = BotStatus.MONITORING
                self.order_side = None
            self._expecting_close_pnl = False
            return

    def initialize(self) -> None:
        if self._initialized:
            return

        tail = self._read_tail(self.TAIL_LINES_ON_INIT)
        for line in tail:
            self._process_line(line)

        try:
            self._position = self.log_file.stat().st_size
            self._last_size = self._position
        except (FileNotFoundError, OSError):
            pass

        self._initialized = True

    def update(self) -> None:
        if not self._initialized:
            self.initialize()

        new_lines = self._read_new_lines()
        for line in new_lines:
            self._process_line(line)

    def get_state(self) -> Dict[str, Any]:
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0.0
        return {
            "status": self.status.value,
            "session_pnl": round(self.session_pnl, 4),
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(win_rate, 1),
            "last_balance": round(self.last_balance, 2),
            "order_side": self.order_side,
            "last_update": self.last_update_time,
        }
