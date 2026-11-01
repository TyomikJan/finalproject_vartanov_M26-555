"""Иерархия валют и реестр поддерживаемых валют."""

from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.utils import (
    MAX_CURRENCY_CODE_LENGTH,
    MIN_CURRENCY_CODE_LENGTH,
    validate_currency_code,
)


class Currency(ABC):
    """Абстрактная валюта с общим интерфейсом отображения.

    Инварианты: code — 2–5 символов в верхнем регистре без пробелов,
    name — непустая строка.
    """

    def __init__(self, name: str, code: str) -> None:
        self.name = name
        self.code = code

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Название валюты не может быть пустым")
        self._name = value.strip()

    @property
    def code(self) -> str:
        return self._code

    @code.setter
    def code(self, value: str) -> None:
        is_valid_code = (
            isinstance(value, str)
            and MIN_CURRENCY_CODE_LENGTH <= len(value) <= MAX_CURRENCY_CODE_LENGTH
            and value.isalnum()
            and value.isupper()
        )
        if not is_valid_code:
            raise ValueError(
                "Код валюты должен состоять из "
                f"{MIN_CURRENCY_CODE_LENGTH}–{MAX_CURRENCY_CODE_LENGTH} "
                f"символов в верхнем регистре без пробелов: '{value}'"
            )
        self._code = value

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть строковое представление валюты для UI и логов."""


class FiatCurrency(Currency):
    """Фиатная валюта, выпускаемая государством или валютным союзом."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        self.issuing_country = issuing_country

    def get_display_info(self) -> str:
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом консенсуса и рыночной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = market_cap

    def get_display_info(self) -> str:
        short_market_cap = f"{self.market_cap:.2e}".replace("+", "")
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {short_market_cap})"
        )


_CURRENCY_REGISTRY: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Ethash", 4.5e11),
    )
}


def get_currency(code: str) -> Currency:
    """Вернуть валюту по коду (регистр не важен).

    Raises:
        ValueError: код имеет некорректный формат.
        CurrencyNotFoundError: код отсутствует в реестре.
    """
    normalized_code = validate_currency_code(code)
    currency = _CURRENCY_REGISTRY.get(normalized_code)
    if currency is None:
        raise CurrencyNotFoundError(normalized_code)
    return currency


def get_supported_codes() -> list[str]:
    """Вернуть коды всех поддерживаемых валют."""
    return list(_CURRENCY_REGISTRY)
