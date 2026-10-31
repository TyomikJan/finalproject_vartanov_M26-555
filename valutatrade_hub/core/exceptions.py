"""Доменные исключения. Текст каждого исключения готов к показу в CLI."""


class ValutaTradeError(Exception):
    """Базовое исключение приложения."""


class NotLoggedInError(ValutaTradeError):
    """Команда требует входа в систему."""

    def __init__(self) -> None:
        super().__init__("Сначала выполните login")


class InsufficientFundsError(ValutaTradeError):
    """На кошельке недостаточно средств для операции."""

    def __init__(self, available: float, required: float, code: str) -> None:
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    """Валюта отсутствует в реестре поддерживаемых валют."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class WalletNotFoundError(ValutaTradeError):
    """У пользователя нет кошелька в указанной валюте."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"У вас нет кошелька '{code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        )


class ApiRequestError(ValutaTradeError):
    """Сбой при получении данных из внешнего источника курсов."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
