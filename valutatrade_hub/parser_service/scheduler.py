"""Периодический запуск обновления курсов: `uv run parser [--interval N] [--once]`."""

import argparse
import logging
import time

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import (
    PARSER_LOGGER_NAME,
    parser_console_output,
    setup_logging,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import build_updater

parser_logger = logging.getLogger(PARSER_LOGGER_NAME)


def run_scheduler(interval_seconds: int, max_runs: int | None = None) -> None:
    """Запускать обновление каждые interval_seconds секунд.

    Ошибка одного запуска логируется и не останавливает планировщик.
    max_runs=None — работать до прерывания (Ctrl+C).
    """
    completed_runs = 0
    while max_runs is None or completed_runs < max_runs:
        try:
            build_updater().run_update()
        except ApiRequestError as error:
            parser_logger.error("Scheduled update failed: %s", error.reason)
        completed_runs += 1
        if max_runs is None or completed_runs < max_runs:
            parser_logger.info("Next update in %d seconds", interval_seconds)
            time.sleep(interval_seconds)


def main() -> None:
    """Точка входа планировщика Parser Service."""
    argument_parser = argparse.ArgumentParser(
        description="Периодическое обновление курсов валют"
    )
    argument_parser.add_argument(
        "--interval",
        type=int,
        default=ParserConfig().update_interval_seconds,
        help="интервал между обновлениями в секундах",
    )
    argument_parser.add_argument(
        "--once", action="store_true", help="выполнить одно обновление и выйти"
    )
    arguments = argument_parser.parse_args()

    setup_logging()
    with parser_console_output():
        try:
            run_scheduler(arguments.interval, max_runs=1 if arguments.once else None)
        except KeyboardInterrupt:
            parser_logger.info("Scheduler stopped")
