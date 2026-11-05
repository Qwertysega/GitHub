import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

from .parser import LogParser, BotStatus


class BotProcess:
    """
    Управляет одним экземпляром бота через subprocess.
    - Запуск/остановка процесса
    - Парсинг торгового лога (trade_history / simulator_history)
    - Чтение системного лога (startup_error.log) напрямую из файла
    - Корректная обработка ручной остановки vs падения
    """

    def __init__(self, bot_dir: Path, symbol: str, timeframe: str, mode: str):
        self.bot_dir = bot_dir
        self.symbol = symbol
        self.timeframe = timeframe
        self.mode = mode

        self.process: Optional[subprocess.Popen] = None
        self.parser: Optional[LogParser] = None

        self._running = False
        self._stopped_manually = True
        self._start_time: float = 0.0

        log_name = "simulator_history.txt" if mode == "sim" else "trade_history.txt"
        self.log_file = bot_dir / log_name
        self.error_log_file = bot_dir / "startup_error.log"

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def uptime_seconds(self) -> float:
        if not self.is_running:
            return 0.0
        return time.time() - self._start_time

    def start(self) -> bool:
        if self.is_running:
            return False

        stderr_file = None
        try:
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'

            stderr_file = open(self.error_log_file, 'a', encoding='utf-8', errors='replace')

            kwargs = {
                'cwd': str(self.bot_dir),
                'stdout': subprocess.DEVNULL,
                'stderr': stderr_file,
                'env': env,
            }

            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                [sys.executable, "bot.py"],
                **kwargs
            )

            self._start_time = time.time()
            self._running = True
            self._stopped_manually = False

            self.parser = LogParser(self.log_file)
            self.parser.initialize()

            return True

        except Exception as e:
            self._write_startup_error(f"Не удалось запустить процесс: {e}")
            return False

        finally:
            # Дескриптор скопирован в дочерний процесс при Popen,
            # поэтому родительскую копию можно (и нужно) закрыть сразу.
            if stderr_file is not None:
                try:
                    stderr_file.close()
                except Exception:
                    pass

            # Обнуляем ссылку, чтобы stop() не пытался закрыть файл повторно.
            if self.process is not None:
                try:
                    self.process.stderr = None
                except Exception:
                    pass

    def stop(self) -> None:
        if not self.is_running:
            return

        self._running = False
        self._stopped_manually = True

        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        except Exception:
            pass

        self.process = None

    def delete(self) -> None:
        self.stop()
        import shutil
        try:
            if self.bot_dir.exists():
                shutil.rmtree(self.bot_dir)
        except Exception as e:
            print(f"Ошибка удаления {self.bot_dir}: {e}")

    def get_state(self) -> Dict[str, Any]:
        state = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "is_running": self.is_running,
            "uptime": self.uptime_seconds,
        }

        if self.parser:
            self.parser.update()
            parser_state = self.parser.get_state()
            state.update(parser_state)

            if not self.is_running:
                if self._stopped_manually:
                    state["status"] = BotStatus.STOPPED.value
                elif parser_state["status"] != BotStatus.STOPPED.value:
                    state["status"] = BotStatus.ERROR.value
        else:
            state["status"] = BotStatus.STOPPED.value
            state["session_pnl"] = 0.0
            state["total_trades"] = 0
            state["wins"] = 0
            state["losses"] = 0
            state["win_rate"] = 0.0
            state["last_balance"] = 0.0

        return state

    def _write_startup_error(self, message: str) -> None:
        try:
            with open(self.error_log_file, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | MANAGER ERROR | {message}\n")
        except Exception:
            pass