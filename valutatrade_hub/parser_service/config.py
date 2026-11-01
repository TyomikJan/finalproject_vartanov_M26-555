"""Конфигурация Parser Service: эндпоинты, списки валют, сетевые параметры.

API-ключ ExchangeRate-API не хранится в коде. Он берётся из переменной
окружения EXCHANGERATE_API_KEY, а если её нет — из файла .env в корне
проекта (файл не отслеживается git). Пример — в .env.example.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    FiatCurrency,
    get_codes_by_type,
)
from valutatrade_hub.infra.settings import SettingsLoader

API_KEY_ENV_NAME = "EXCHANGERATE_API_KEY"

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"

BASE_FIAT_CURRENCY = "USD"
# Списки валют берутся из реестра currencies.py, чтобы парсер загружал
# ровно те курсы, которые знает Core.
FIAT_CURRENCIES = tuple(
    code for code in get_codes_by_type(FiatCurrency) if code != BASE_FIAT_CURRENCY
)
CRYPTO_CURRENCIES = get_codes_by_type(CryptoCurrency)
CRYPTO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}

REQUEST_TIMEOUT_SECONDS = 10


def load_api_key() -> str | None:
    """Вернуть ключ ExchangeRate-API из окружения или файла .env.

    load_dotenv не перезаписывает уже заданные переменные окружения,
    поэтому они имеют приоритет над .env.
    """
    load_dotenv(SettingsLoader().get("env_file"))
    return os.getenv(API_KEY_ENV_NAME)


@dataclass(frozen=True)
class ParserConfig:
    """Настройки Parser Service, собранные в одном объекте."""

    exchangerate_api_key: str | None = field(default_factory=load_api_key)
    coingecko_url: str = COINGECKO_URL
    exchangerate_api_url: str = EXCHANGERATE_API_URL
    base_currency: str = BASE_FIAT_CURRENCY
    fiat_currencies: tuple[str, ...] = FIAT_CURRENCIES
    crypto_currencies: tuple[str, ...] = CRYPTO_CURRENCIES
    crypto_id_map: dict[str, str] = field(default_factory=lambda: dict(CRYPTO_ID_MAP))
    request_timeout: int = REQUEST_TIMEOUT_SECONDS
    rates_file_path: Path = field(
        default_factory=lambda: SettingsLoader().get("rates_file")
    )
    history_file_path: Path = field(
        default_factory=lambda: SettingsLoader().get("exchange_rates_file")
    )
    update_interval_seconds: int = field(
        default_factory=lambda: SettingsLoader().get("update_interval_seconds")
    )
