"""Вспомогательные функции: валидация входных данных, форматирование, хеширование."""

import hashlib
import math
import secrets

MIN_CURRENCY_CODE_LENGTH = 2
MAX_CURRENCY_CODE_LENGTH = 5


def validate_currency_code(currency_code: str) -> str:
    """Проверить формат кода валюты и привести его к верхнему регистру.

    Код должен состоять из 2–5 букв или цифр без пробелов.
    """
    if not isinstance(currency_code, str) or not currency_code.strip():
        raise ValueError("Код валюты должен быть непустой строкой")
    normalized_code = currency_code.strip().upper()
    is_valid_length = (
        MIN_CURRENCY_CODE_LENGTH <= len(normalized_code) <= MAX_CURRENCY_CODE_LENGTH
    )
    if not normalized_code.isalnum() or not is_valid_length:
        raise ValueError(f"Некорректный код валюты '{currency_code}'")
    return normalized_code


def parse_amount(amount: float | str) -> float:
    """Преобразовать сумму в float и убедиться, что она положительна."""
    error_message = "'amount' должен быть положительным числом"
    if isinstance(amount, bool):
        raise ValueError(error_message)
    try:
        parsed_amount = float(amount)
    except (TypeError, ValueError) as error:
        raise ValueError(error_message) from error
    if not math.isfinite(parsed_amount) or parsed_amount <= 0:
        raise ValueError(error_message)
    return parsed_amount


def format_rate(rate: float) -> str:
    """Отформатировать курс: мелкие значения показываются с большей точностью."""
    return f"{rate:.2f}" if rate >= 1 else f"{rate:.8f}"


def generate_salt(length_bytes: int = 8) -> str:
    """Сгенерировать случайную соль в виде hex-строки."""
    return secrets.token_hex(length_bytes)


def hash_password(password: str, salt: str) -> str:
    """Вернуть односторонний хеш sha256(password + salt)."""
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
