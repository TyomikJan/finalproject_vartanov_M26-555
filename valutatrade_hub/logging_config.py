"""Настройка логирования доменных операций.

Формат — человекочитаемая строка:
    INFO 2025-10-09T12:05:22 BUY user='alice' currency='BTC' amount=0.0500 ...
Логи пишутся в файл из настройки log_file с ротацией по размеру
(log_max_bytes, log_backup_count). Уровень по умолчанию — INFO,
для отладки в [tool.valutatrade] можно указать log_level = "DEBUG".
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

ACTIONS_LOGGER_NAME = "valutatrade_hub.actions"
LOG_FORMAT = "%(levelname)s %(asctime)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging() -> logging.Logger:
    """Подключить файловый обработчик с ротацией к логгеру операций."""
    settings = SettingsLoader()
    logger = logging.getLogger(ACTIONS_LOGGER_NAME)
    logger.setLevel(settings.get("log_level", "INFO"))
    if logger.handlers:
        # Повторный вызов не добавляет второй обработчик.
        return logger

    log_file = Path(settings.get("log_file"))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.get("log_max_bytes"),
        backupCount=settings.get("log_backup_count"),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.addHandler(handler)
    # Логи операций не должны дублироваться в консоль CLI через root-логгер.
    logger.propagate = False
    return logger
