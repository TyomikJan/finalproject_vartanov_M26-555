"""Декораторы для сквозной функциональности (логирование операций)."""

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from valutatrade_hub.core.utils import format_rate
from valutatrade_hub.logging_config import ACTIONS_LOGGER_NAME

actions_logger = logging.getLogger(ACTIONS_LOGGER_NAME)


def _format_amount(amount: Any) -> str:
    try:
        return f"{float(amount):.4f}"
    except (TypeError, ValueError):
        return repr(amount)


def _describe_call(arguments: dict[str, Any]) -> list[str]:
    fields = []
    user = arguments.get("user")
    username = getattr(user, "username", None) or arguments.get("username")
    fields.append(f"user={username!r}")
    if "currency_code" in arguments:
        fields.append(f"currency={str(arguments['currency_code']).upper()!r}")
    if "amount" in arguments:
        fields.append(f"amount={_format_amount(arguments['amount'])}")
    return fields


def _describe_result(result: Any, verbose: bool) -> list[str]:
    fields = []
    if hasattr(result, "rate"):
        fields.append(f"rate={format_rate(result.rate)}")
    if hasattr(result, "base_currency"):
        fields.append(f"base={result.base_currency!r}")
    if verbose and hasattr(result, "balance_changes"):
        changes = "; ".join(
            f"{change.currency_code} {change.balance_before:.4f}"
            f"→{change.balance_after:.4f}"
            for change in result.balance_changes
        )
        fields.append(f"changes='{changes}'")
    return fields


def log_action(action: str, verbose: bool = False) -> Callable:
    """Логировать вызов доменной операции на уровне INFO.

    В запись попадают action, пользователь, валюта и сумма из аргументов,
    курс и базовая валюта из результата, а также result=OK или
    result=ERROR с типом и текстом исключения. Исключение не глотается,
    а пробрасывается дальше. При verbose=True добавляются изменения
    балансов кошельков «было→стало».
    """

    def decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            arguments = signature.bind_partial(*args, **kwargs).arguments
            fields = [action, *_describe_call(arguments)]
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                fields += [
                    "result=ERROR",
                    f"error_type={type(error).__name__}",
                    f"error_message={str(error)!r}",
                ]
                actions_logger.info(" ".join(fields))
                raise
            fields += [*_describe_result(result, verbose), "result=OK"]
            actions_logger.info(" ".join(fields))
            return result

        return wrapper

    return decorator
