"""Доменные исключения. Текст каждого исключения готов к показу в CLI."""


class ValutaTradeError(Exception):
    """Базовое исключение приложения."""


class NotLoggedInError(ValutaTradeError):
    """Команда требует входа в систему."""

    def __init__(self) -> None:
        super().__init__("Сначала выполните login")


class UsernameTakenError(ValutaTradeError):
    """Имя пользователя уже занято."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"Имя пользователя '{username}' уже занято")


class UserNotFoundError(ValutaTradeError):
    """Пользователь с таким именем или id не найден."""

    def __init__(self, user_reference: str | int) -> None:
        self.user_reference = user_reference
        super().__init__(f"Пользователь '{user_reference}' не найден")


class InvalidPasswordError(ValutaTradeError):
    """Пароль не совпадает с сохранённым хешем."""

    def __init__(self) -> None:
        super().__init__("Неверный пароль")


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


class RatesCacheEmptyError(ValutaTradeError):
    """Локальный кеш курсов пуст или ещё не создан."""

    def __init__(self) -> None:
        super().__init__(
            "Локальный кеш курсов пуст. "
            "Выполните 'update-rates', чтобы загрузить данные."
        )


class RateNotFoundError(ValutaTradeError):
    """В кеше нет курса для запрошенной валюты."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Курс для '{code}' не найден в кеше.")
