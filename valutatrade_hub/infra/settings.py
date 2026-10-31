"""Конфигурация приложения: единственный экземпляр SettingsLoader."""

import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"
CONFIG_SECTION = "valutatrade"
PATH_KEYS = {"data_dir", "users_file", "portfolios_file", "rates_file", "log_file"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "data_dir": "data",
    "users_file": "data/users.json",
    "portfolios_file": "data/portfolios.json",
    "rates_file": "data/rates.json",
    "rates_ttl_seconds": 300,
    "default_base_currency": "USD",
    "log_file": "logs/actions.log",
    "log_level": "INFO",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 5,
}


class SettingsLoader:
    """Загружает и кеширует конфигурацию из секции [tool.valutatrade].

    Значения из pyproject.toml перекрывают DEFAULT_SETTINGS, относительные
    пути разрешаются от корня проекта. Если pyproject.toml недоступен
    (например, пакет установлен как wheel), используются значения по умолчанию.
    """

    # Singleton через __new__: это проще и читабельнее метакласса, а повторные
    # вызовы SettingsLoader() в разных модулях возвращают тот же объект.
    _instance: "SettingsLoader | None" = None

    def __new__(cls) -> "SettingsLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._settings = {}
            cls._instance.reload()
        return cls._instance

    def reload(self) -> None:
        """Перечитать конфигурацию с диска."""
        settings = dict(DEFAULT_SETTINGS)
        settings.update(self._read_pyproject_section())
        for key in PATH_KEYS & settings.keys():
            settings[key] = PROJECT_ROOT / settings[key]
        self._settings = settings

    def get(self, key: str, default: Any = None) -> Any:
        """Вернуть значение настройки или default, если ключа нет."""
        return self._settings.get(key, default)

    @staticmethod
    def _read_pyproject_section() -> dict[str, Any]:
        try:
            with PYPROJECT_FILE.open("rb") as file:
                pyproject = tomllib.load(file)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return {}
        return pyproject.get("tool", {}).get(CONFIG_SECTION, {})
