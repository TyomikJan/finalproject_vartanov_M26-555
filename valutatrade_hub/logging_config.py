"""Настройка логирования.

Два логгера:
- операции пользователя (register/login/buy/sell) → log_file, строка вида
    INFO 2025-10-09T12:05:22 BUY user='alice' currency='BTC' amount=0.0500 ...
- Parser Service → parser_log_file на уровне DEBUG с подробным форматом
  (время, уровень, имя логгера, причина ошибки с traceback). В консоль
  его логи выводятся только внутри parser_console_output(), например
  на время команды update-rates, в виде "INFO: Starting rates update...".
Файлы ротируются по размеру (log_max_bytes, log_backup_count).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

ACTIONS_LOGGER_NAME = "valutatrade_hub.actions"
PARSER_LOGGER_NAME = "valutatrade_hub.parser"
ACTIONS_LOG_FORMAT = "%(levelname)s %(asctime)s %(message)s"
PARSER_FILE_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
CONSOLE_LOG_FORMAT = "%(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _create_file_handler(
    log_file: Path, log_format: str, level: int | str
) -> RotatingFileHandler:
    settings = SettingsLoader()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.get("log_max_bytes"),
        backupCount=settings.get("log_backup_count"),
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(log_format, datefmt=LOG_DATE_FORMAT))
    return handler


def _configure_logger(name: str, level: int | str, handler: logging.Handler) -> None:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    # Логи не должны дублироваться через root-логгер.
    logger.propagate = False


def setup_logging() -> None:
    """Подключить файловые обработчики к логгерам операций и Parser Service."""
    if logging.getLogger(ACTIONS_LOGGER_NAME).handlers:
        # Повторный вызов не добавляет вторые обработчики.
        return
    settings = SettingsLoader()
    actions_level = settings.get("log_level", "INFO")
    _configure_logger(
        ACTIONS_LOGGER_NAME,
        actions_level,
        _create_file_handler(
            Path(settings.get("log_file")), ACTIONS_LOG_FORMAT, actions_level
        ),
    )
    _configure_logger(
        PARSER_LOGGER_NAME,
        logging.DEBUG,
        _create_file_handler(
            Path(settings.get("parser_log_file")),
            PARSER_FILE_LOG_FORMAT,
            logging.DEBUG,
        ),
    )


@contextmanager
def parser_console_output() -> Iterator[None]:
    """Временно выводить логи Parser Service в консоль (INFO, короткий формат)."""
    parser_logger = logging.getLogger(PARSER_LOGGER_NAME)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(CONSOLE_LOG_FORMAT))
    parser_logger.addHandler(console_handler)
    try:
        yield
    finally:
        parser_logger.removeHandler(console_handler)
