"""Доменные модели: пользователь, кошелёк и портфель."""

from datetime import datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import generate_salt, hash_password, parse_amount

MIN_PASSWORD_LENGTH = 4
BASE_CURRENCY = "USD"

EXCHANGE_RATES_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "RUB": 0.011,
    "BTC": 60000.0,
    "ETH": 3000.0,
}


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


class User:
    """Пользователь системы."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        self._user_id = user_id
        # username без подчеркивания чтобы работал setter
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        """Создать нового пользователя из открытого пароля."""
        _validate_password(password)
        salt = generate_salt()
        return cls(
            user_id=user_id,
            username=username,
            hashed_password=hash_password(password, salt),
            salt=salt,
            registration_date=datetime.now(),
        )

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        return self._hashed_password

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    def get_user_info(self) -> dict[str, str | int]:
        """Вернуть публичную информацию о пользователе (без пароля и соли)."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Сменить пароль, сгенерировав новую соль и хеш."""
        _validate_password(new_password)
        self._salt = generate_salt()
        self._hashed_password = hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Проверить, совпадает ли пароль с сохранённым хешем."""
        return hash_password(password, self._salt) == self._hashed_password

    def to_dict(self) -> dict[str, str | int]:
        """Сериализовать пользователя для users.json."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": self._registration_date.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Восстановить пользователя из записи users.json."""
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=datetime.fromisoformat(data["registration_date"]),
        )


class Wallet:
    """Кошелёк пользователя для одной конкретной валюты."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        self._currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def currency_code(self) -> str:
        return self._currency_code

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Баланс должен быть числом")
        if value < 0:
            raise ValueError("Баланс не может быть отрицательным")
        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        """Пополнить баланс на положительную сумму."""
        self.balance += parse_amount(amount)

    def withdraw(self, amount: float) -> None:
        """Снять положительную сумму, не превышающую баланс."""
        amount = parse_amount(amount)
        if amount > self._balance:
            raise InsufficientFundsError(self._balance, amount, self._currency_code)
        self.balance -= amount

    def get_balance_info(self) -> str:
        """Вернуть строку с текущим балансом кошелька."""
        return f"{self.currency_code}: {self._balance:.4f}"

    def to_dict(self) -> dict[str, str | float]:
        return {"currency_code": self.currency_code, "balance": self._balance}


class Portfolio:
    """Набор кошельков одного пользователя."""

    def __init__(self, user: User, wallets: dict[str, Wallet] | None = None) -> None:
        self._user = user
        self._user_id = user.user_id
        self._wallets: dict[str, Wallet] = dict(wallets) if wallets else {}

    @property
    def user(self) -> User:
        return self._user

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря кошельков: изменения в ней не затрагивают портфель."""
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        """Добавить пустой кошелёк новой валюты и вернуть его."""
        currency_code = get_currency(currency_code).code
        if currency_code in self._wallets:
            raise ValueError(f"Кошелёк {currency_code} уже есть в портфеле")

        wallet = Wallet(currency_code)
        self._wallets[currency_code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet | None:
        """Вернуть кошелёк по коду валюты или None, если его нет."""
        return self._wallets.get(get_currency(currency_code).code)

    def get_total_value(
        self,
        base_currency: str = BASE_CURRENCY,
        exchange_rates: dict[str, float] | None = None,
    ) -> float:
        """Посчитать стоимость всех кошельков в базовой валюте.

        exchange_rates — курсы валют к USD; по умолчанию EXCHANGE_RATES_TO_USD.
        """
        rates = exchange_rates or EXCHANGE_RATES_TO_USD
        base_currency = get_currency(base_currency).code
        if base_currency not in rates:
            raise ValueError(f"Нет курса для базовой валюты: {base_currency}")

        total_in_usd = 0.0
        for currency_code, wallet in self._wallets.items():
            if currency_code not in rates:
                raise ValueError(f"Нет курса для валюты: {currency_code}")
            total_in_usd += wallet.balance * rates[currency_code]
        return total_in_usd / rates[base_currency]

    def to_dict(self) -> dict:
        """Сериализовать портфель для portfolios.json."""
        return {
            "user_id": self._user_id,
            "wallets": {
                currency_code: {"balance": wallet.balance}
                for currency_code, wallet in self._wallets.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict, user: User) -> "Portfolio":
        """Восстановить портфель владельца user из записи portfolios.json."""
        if data["user_id"] != user.user_id:
            raise ValueError(
                f"Портфель принадлежит пользователю {data['user_id']}, "
                f"а не {user.user_id}"
            )
        wallets = {
            currency_code: Wallet(currency_code, wallet_data["balance"])
            for currency_code, wallet_data in data.get("wallets", {}).items()
        }
        return cls(user=user, wallets=wallets)
