"""Клиенты внешних API курсов с единым форматом ответа {"BTC_USD": 59337.21}."""

import logging
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME
from valutatrade_hub.parser_service.config import ParserConfig

HTTP_OK = 200
HTTP_ERROR_REASONS = {
    401: "неверный или отсутствующий API-ключ (401)",
    403: "доступ запрещён, проверьте API-ключ (403)",
    404: "эндпоинт не найден (404)",
    429: "превышен лимит запросов, повторите позже (429)",
}
MAX_LOGGED_BODY_LENGTH = 300
EXCHANGERATE_ERROR_REASONS = {
    "invalid-key": "неверный API-ключ",
    "inactive-account": "аккаунт не активирован",
    "quota-reached": "исчерпан лимит запросов тарифа",
    "unsupported-code": "неподдерживаемый код валюты",
}


api_logger = logging.getLogger(f"{PARSER_LOGGER_NAME}.api_clients")


@dataclass(frozen=True)
class RequestMeta:
    """Технические сведения о последнем запросе для истории замеров."""

    request_ms: int
    status_code: int
    etag: str | None


def _validate_rate(value: Any, pair_key: str) -> float:
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not is_number or not math.isfinite(value) or value <= 0:
        raise ApiRequestError(f"некорректное значение курса {pair_key}: {value!r}")
    return float(value)


class BaseApiClient(ABC):
    """Общий интерфейс клиента: fetch_rates() возвращает курсы к базовой валюте."""

    source_name: str

    def __init__(self, config: ParserConfig) -> None:
        self.config = config
        self.last_request_meta: RequestMeta | None = None

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Вернуть курсы вида {"<КОД>_<БАЗА>": курс}.

        Raises:
            ApiRequestError: сеть недоступна, API вернул ошибку или
                ответ имеет неожиданный формат.
        """

    def _mask_secrets(self, url: str) -> str:
        """Вернуть URL, пригодный для логов (без API-ключа)."""
        return url

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> dict:
        """Выполнить GET-запрос и вернуть JSON, переводя сбои в ApiRequestError."""
        api_logger.debug("GET %s params=%s", self._mask_secrets(url), params)
        started_at = time.perf_counter()
        try:
            response = requests.get(
                url, params=params, timeout=self.config.request_timeout
            )
        except requests.exceptions.Timeout as error:
            raise ApiRequestError(
                f"истёк таймаут {self.config.request_timeout} с"
            ) from error
        except requests.exceptions.RequestException as error:
            raise ApiRequestError("ошибка сети") from error

        self.last_request_meta = RequestMeta(
            request_ms=round((time.perf_counter() - started_at) * 1000),
            status_code=response.status_code,
            etag=response.headers.get("ETag"),
        )
        api_logger.debug(
            "%s responded %d in %d ms",
            self.source_name,
            response.status_code,
            self.last_request_meta.request_ms,
        )
        if response.status_code != HTTP_OK:
            api_logger.debug(
                "%s error body: %s",
                self.source_name,
                response.text[:MAX_LOGGED_BODY_LENGTH],
            )
            reason = HTTP_ERROR_REASONS.get(
                response.status_code, f"HTTP {response.status_code}"
            )
            raise ApiRequestError(reason)
        try:
            return response.json()
        except ValueError as error:
            raise ApiRequestError("ответ не JSON") from error


class CoinGeckoClient(BaseApiClient):
    """Курсы криптовалют из CoinGecko (публичный доступ без ключа)."""

    source_name = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        base_code = self.config.base_currency
        coin_ids = [
            self.config.crypto_id_map[code] for code in self.config.crypto_currencies
        ]
        payload = self._get_json(
            self.config.coingecko_url,
            params={"ids": ",".join(coin_ids), "vs_currencies": base_code.lower()},
        )

        rates = {}
        for code in self.config.crypto_currencies:
            pair_key = f"{code}_{base_code}"
            price = payload.get(self.config.crypto_id_map[code], {}).get(
                base_code.lower()
            )
            if price is None:
                raise ApiRequestError(f"нет курса {pair_key}")
            rates[pair_key] = _validate_rate(price, pair_key)
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Курсы фиатных валют из ExchangeRate-API (нужен API-ключ)."""

    source_name = "ExchangeRate-API"

    def _mask_secrets(self, url: str) -> str:
        api_key = self.config.exchangerate_api_key
        return url.replace(api_key, "***") if api_key else url

    def fetch_rates(self) -> dict[str, float]:
        api_key = self.config.exchangerate_api_key
        if not api_key:
            raise ApiRequestError(
                "не задан ключ EXCHANGERATE_API_KEY "
                "(переменная окружения или файл .env)"
            )
        base_code = self.config.base_currency
        payload = self._get_json(
            f"{self.config.exchangerate_api_url}/{api_key}/latest/{base_code}"
        )
        if payload.get("result") != "success":
            error_type = payload.get("error-type", "неизвестная ошибка")
            reason = EXCHANGERATE_ERROR_REASONS.get(error_type, error_type)
            raise ApiRequestError(reason)

        # API отвечает «за 1 USD дают 0.8956 EUR» (курс USD→EUR), а в кеше
        # хранится обратный курс EUR→USD, поэтому берём 1 / значение.
        # В API v6 курсы лежат в conversion_rates, в примере из задания — в rates.
        base_to_currency_rates = payload.get("conversion_rates") or payload.get(
            "rates", {}
        )
        rates = {}
        for code in self.config.fiat_currencies:
            pair_key = f"{code}_{base_code}"
            base_to_currency = _validate_rate(
                base_to_currency_rates.get(code), pair_key
            )
            rates[pair_key] = 1 / base_to_currency
        return rates
