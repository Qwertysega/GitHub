import shutil
import re
from pathlib import Path
from typing import Dict, Any, Optional

from .settings import SettingsManager


class BotFactory:
    """
    Создание нового бота из шаблона.
    - Копирует bot.py, exchange.py, simulator.py, filters.py из bot_templates/
    - Генерирует config.py из config_template.py с подстановкой значений
    - Автоинкрементирует имя папки (OPUSDT_M5_sim1, sim2, ...)
    """

    TEMPLATE_DIR_NAME = "bot_templates"
    BOTS_DIR_NAME = "bots"
    CONFIG_TEMPLATE_NAME = "config_template.py"

    # Файлы, которые копируются из шаблона в папку бота
    COPY_FILES = ["bot.py", "exchange.py", "simulator.py", "filters.py"]

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.template_dir = self.base_dir / self.TEMPLATE_DIR_NAME
        self.bots_dir = self.base_dir / self.BOTS_DIR_NAME
        self.settings = SettingsManager(self.base_dir)

    def _generate_bot_name(self, symbol: str, timeframe: str, mode: str) -> str:
        """
        Генерирует уникальное имя папки бота.
        Формат: {SYMBOL}_{TIMEFRAME}_{MODE}{INDEX}
        Пример: OPUSDT_M5_sim1, BTCUSDT_M15_live1
        """
        prefix = f"{symbol}_{timeframe}_{mode}"
        existing = []

        if self.bots_dir.exists():
            for d in self.bots_dir.iterdir():
                if d.is_dir() and d.name.startswith(prefix):
                    # Извлекаем индекс из имени
                    match = re.search(rf'^{re.escape(prefix)}(\d+)$', d.name)
                    if match:
                        existing.append(int(match.group(1)))

        next_index = max(existing, default=0) + 1
        return f"{prefix}{next_index}"

    def create_bot(
        self,
        symbol: str,
        timeframe: str,
        mode: str,  # "sim" или "live"
        custom_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        Создаёт нового бота.
        Возвращает путь к папке бота или None при ошибке.
        """
        bot_name = self._generate_bot_name(symbol, timeframe, mode)
        bot_dir = self.bots_dir / bot_name

        if bot_dir.exists():
            print(f"❌ Папка {bot_dir} уже существует!")
            return None

        # Проверяем наличие шаблона
        config_template = self.template_dir / self.CONFIG_TEMPLATE_NAME
        if not config_template.exists():
            print(f"❌ Шаблон конфига не найден: {config_template}")
            return None

        try:
            # 1. Создаём папку бота
            bot_dir.mkdir(parents=True, exist_ok=True)

            # 2. Копируем рабочие файлы из шаблона
            for filename in self.COPY_FILES:
                src = self.template_dir / filename
                dst = bot_dir / filename
                if src.exists():
                    shutil.copy2(src, dst)
                else:
                    print(f"⚠️ Файл шаблона отсутствует: {src}")

            # 3. Генерируем config.py из шаблона
            defaults = self.settings.get_defaults_for_new_bot()
            params = {
                "SYMBOL": symbol,
                "TIMEFRAME": timeframe,
                "CATEGORY": "linear",
                "SIMULATOR_MODE": mode == "sim",
                **defaults,
            }
            if custom_params:
                params.update(custom_params)

            template_content = config_template.read_text(encoding="utf-8")
            config_content = template_content
            for key, value in params.items():
                placeholder = "{{" + key + "}}"
                # Корректная подстановка Python-литералов
                if isinstance(value, bool):
                    replacement = "True" if value else "False"
                elif isinstance(value, str):
                    replacement = f'"{value}"'
                else:
                    replacement = str(value)
                config_content = config_content.replace(placeholder, replacement)

            (bot_dir / "config.py").write_text(config_content, encoding="utf-8")

            # 4. Создаём пустые лог-файлы
            for log_name in ["trade_history.txt", "simulator_history.txt", "startup_error.log"]:
                (bot_dir / log_name).touch(exist_ok=True)

            print(f"✅ Бот создан: {bot_name}")
            return bot_dir

        except Exception as e:
            print(f"❌ Ошибка создания бота: {e}")
            # Откат: удаляем частично созданную папку
            if bot_dir.exists():
                shutil.rmtree(bot_dir, ignore_errors=True)
            return None

    def list_bots(self) -> list:
        """Возвращает список всех созданных ботов с метаданными."""
        bots = []
        if not self.bots_dir.exists():
            return bots

        for d in sorted(self.bots_dir.iterdir()):
            if not d.is_dir():
                continue
            # Парсим имя папки
            parts = d.name.rsplit("_", 2)
            if len(parts) >= 3:
                symbol = parts[0]
                timeframe = parts[1]
                mode_idx = parts[2]
                # Режим может быть sim1, live2 и т.д.
                mode_match = re.match(r'(sim|live)(\d+)', mode_idx)
                mode = mode_match.group(1) if mode_match else "unknown"
                index = int(mode_match.group(2)) if mode_match else 0
            else:
                symbol, timeframe, mode, index = d.name, "?", "?", 0

            bots.append({
                "name": d.name,
                "path": d,
                "symbol": symbol,
                "timeframe": timeframe,
                "mode": mode,
                "index": index,
            })

        return bots
