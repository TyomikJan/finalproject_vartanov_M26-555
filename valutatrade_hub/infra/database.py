"""Доступ к JSON-хранилищу: единственный экземпляр DatabaseManager."""

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader

COLLECTION_DEFAULTS: dict[str, list | dict] = {
    "users": [],
    "portfolios": [],
    "rates": {},
}


class DatabaseManager:
    """Чтение и запись коллекций users, portfolios и rates.

    Путь к файлу каждой коллекции берётся из SettingsLoader
    (ключ "<коллекция>_file"). Запись атомарна: данные пишутся во временный
    файл, который затем заменяет основной, поэтому сбой посреди записи
    не оставляет повреждённый JSON.
    """

    # Singleton через __new__, как и SettingsLoader: одна точка доступа к данным.
    _instance: "DatabaseManager | None" = None

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def read(self, collection: str) -> Any:
        """Прочитать коллекцию; если файла нет или он повреждён — пустое значение."""
        try:
            with self._path(collection).open(encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            # возвращает пустой список/словарь в случае ошибки
            return COLLECTION_DEFAULTS[collection].copy()

    def write(self, collection: str, data: Any) -> None:
        """Атомарно записать коллекцию целиком."""
        path = self._path(collection)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def update(self, collection: str, modify: Callable[[Any], Any]) -> Any:
        """Прочитать коллекцию, изменить её функцией modify и записать результат.

        Если modify бросает исключение, файл остаётся без изменений.
        """
        updated_data = modify(self.read(collection))
        self.write(collection, updated_data)
        return updated_data

    @staticmethod
    def _path(collection: str) -> Path:
        if collection not in COLLECTION_DEFAULTS:
            raise KeyError(f"Неизвестная коллекция '{collection}'")
        return Path(SettingsLoader().get(f"{collection}_file"))
