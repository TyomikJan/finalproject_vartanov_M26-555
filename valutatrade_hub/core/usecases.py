"""Бизнес-логика приложения: пользователи, портфели, сделки и курсы валют.

Конфигурация берётся из синглтона SettingsLoader (базовая валюта, TTL курсов),
данные читаются и пишутся через синглтон DatabaseManager. Операции
register, login, buy и sell логируются декоратором @log_action.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    NotLoggedInError,
    WalletNotFoundError,
)
from valutatrade_hub.core.models import EXCHANGE_RATES_TO_USD, Portfolio, User, Wallet
from valutatrade_hub.core.utils import parse_amount
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader

RATES_SOURCE = "ParserServiceStub"  # заглушка

settings = SettingsLoader()
database = DatabaseManager()


# Dataclass для обмена данными с модулем CLI


@dataclass(frozen=True)
class RateInfo:
    from_code: str
    to_code: str
    rate: float
    updated_at: datetime

    @property
    def inverse_rate(self) -> float:
        return 1 / self.rate


@dataclass(frozen=True)
class WalletValue:
    currency_code: str
    balance: float
    value_in_base: float


@dataclass(frozen=True)
class PortfolioReport:
    username: str
    base_currency: str
    wallets: list[WalletValue]

    @property
    def total_value(self) -> float:
        return sum(wallet.value_in_base for wallet in self.wallets)


@dataclass(frozen=True)
class BalanceChange:
    currency_code: str
    balance_before: float
    balance_after: float


@dataclass(frozen=True)
class TradeResult:
    """Итог сделки: курс и изменения балансов затронутых кошельков."""

    currency_code: str
    amount: float
    rate: float
    base_currency: str
    balance_changes: list[BalanceChange]

    @property
    def estimated_value(self) -> float:
        return self.amount * self.rate


def _base_currency() -> str:
    return settings.get("default_base_currency")


def _load_users() -> list[User]:
    return [User.from_dict(record) for record in database.read("users")]


def _find_user(username: str) -> User | None:
    return next((user for user in _load_users() if user.username == username), None)


def _load_portfolio(user: User) -> Portfolio:
    for record in database.read("portfolios"):
        if record["user_id"] == user.user_id:
            return Portfolio.from_dict(record, user)
    return Portfolio(user)


def _save_portfolio(portfolio: Portfolio) -> None:
    def replace_record(records: list[dict]) -> list[dict]:
        other_records = [
            record for record in records if record["user_id"] != portfolio.user_id
        ]
        return [*other_records, portfolio.to_dict()]

    database.update("portfolios", replace_record)


def _require_login(user: User | None) -> User:
    if user is None:
        raise NotLoggedInError()
    return user


@log_action("REGISTER")
def register(username: str, password: str) -> User:
    """Зарегистрировать пользователя и создать ему пустой портфель."""

    def add_user(records: list[dict]) -> list[dict]:
        if any(record["username"] == username.strip() for record in records):
            raise ValueError(f"Имя пользователя '{username}' уже занято")
        next_user_id = max((record["user_id"] for record in records), default=0) + 1
        user = User.create(user_id=next_user_id, username=username, password=password)
        return [*records, user.to_dict()]

    updated_records = database.update("users", add_user)
    user = User.from_dict(updated_records[-1])
    _save_portfolio(Portfolio(user))
    return user


@log_action("LOGIN")
def login(username: str, password: str) -> User:
    """Найти пользователя и проверить его пароль."""
    user = _find_user(username)
    if user is None:
        raise ValueError(f"Пользователь '{username}' не найден")
    if not user.verify_password(password):
        raise ValueError("Неверный пароль")
    return user


def _fetch_rate_from_source(from_code: str, to_code: str) -> float:
    """Заглушка Parser Service: кросс-курс через фиксированные курсы к USD."""
    if from_code not in EXCHANGE_RATES_TO_USD or to_code not in EXCHANGE_RATES_TO_USD:
        raise ApiRequestError(f"нет данных о курсе {from_code}→{to_code}")
    return EXCHANGE_RATES_TO_USD[from_code] / EXCHANGE_RATES_TO_USD[to_code]


def get_rate(from_code: str, to_code: str) -> RateInfo:
    """Вернуть курс from_code → to_code и время его обновления.

    Свежий курс (моложе rates_ttl_seconds из настроек) берётся из кеша
    rates.json, иначе запрашивается у источника и кеш обновляется.

    Raises:
        CurrencyNotFoundError: один из кодов не поддерживается.
        ApiRequestError: кеш устарел, а источник не смог вернуть курс.
    """
    from_code = get_currency(from_code).code
    to_code = get_currency(to_code).code
    now = datetime.now()
    if from_code == to_code:
        return RateInfo(from_code, to_code, 1.0, now)

    pair_key = f"{from_code}_{to_code}"
    cached_entry = database.read("rates").get(pair_key)
    if cached_entry:
        updated_at = datetime.fromisoformat(cached_entry["updated_at"])
        rates_ttl = timedelta(seconds=settings.get("rates_ttl_seconds"))
        if now - updated_at < rates_ttl:
            return RateInfo(from_code, to_code, cached_entry["rate"], updated_at)

    fresh_rate = _fetch_rate_from_source(from_code, to_code)

    def store_rate(rates: dict) -> dict:
        rates[pair_key] = {"rate": fresh_rate, "updated_at": now.isoformat()}
        rates["source"] = RATES_SOURCE
        rates["last_refresh"] = now.isoformat()
        return rates

    database.update("rates", store_rate)
    return RateInfo(from_code, to_code, fresh_rate, now)


def show_portfolio(
    user: User | None, base_currency: str | None = None
) -> PortfolioReport:
    """Собрать балансы кошельков и их стоимость в базовой валюте."""
    user = _require_login(user)
    base_currency = get_currency(base_currency or _base_currency()).code
    wallet_values = [
        WalletValue(
            currency_code=currency_code,
            balance=wallet.balance,
            value_in_base=wallet.balance * get_rate(currency_code, base_currency).rate,
        )
        for currency_code, wallet in _load_portfolio(user).wallets.items()
    ]
    return PortfolioReport(user.username, base_currency, wallet_values)


def _get_or_create_wallet(portfolio: Portfolio, currency_code: str) -> Wallet:
    return portfolio.get_wallet(currency_code) or portfolio.add_currency(currency_code)


def _change_balance(
    wallet: Wallet, amount: float, operation: Callable[[float], None]
) -> BalanceChange:
    balance_before = wallet.balance
    operation(amount)
    return BalanceChange(wallet.currency_code, balance_before, wallet.balance)


@log_action("BUY", verbose=True)
def buy(user: User | None, currency_code: str, amount: float | str) -> TradeResult:
    """Купить amount единиц валюты; кошелёк создаётся при первой покупке."""
    user = _require_login(user)
    currency_code = get_currency(currency_code).code
    amount = parse_amount(amount)
    base_currency = _base_currency()
    rate = get_rate(currency_code, base_currency).rate

    portfolio = _load_portfolio(user)
    wallet = _get_or_create_wallet(portfolio, currency_code)
    balance_changes = [_change_balance(wallet, amount, wallet.deposit)]
    _save_portfolio(portfolio)
    return TradeResult(currency_code, amount, rate, base_currency, balance_changes)


@log_action("SELL", verbose=True)
def sell(user: User | None, currency_code: str, amount: float | str) -> TradeResult:
    """Продать amount единиц валюты; выручка зачисляется на кошелёк базовой валюты.

    Raises:
        WalletNotFoundError: кошелька в этой валюте нет.
        InsufficientFundsError: на кошельке меньше, чем amount.
    """
    user = _require_login(user)
    currency_code = get_currency(currency_code).code
    amount = parse_amount(amount)
    base_currency = _base_currency()

    portfolio = _load_portfolio(user)
    wallet = portfolio.get_wallet(currency_code)
    if wallet is None:
        raise WalletNotFoundError(currency_code)
    rate = get_rate(currency_code, base_currency).rate
    balance_changes = [_change_balance(wallet, amount, wallet.withdraw)]
    if currency_code != base_currency:
        base_wallet = _get_or_create_wallet(portfolio, base_currency)
        balance_changes.append(
            _change_balance(base_wallet, amount * rate, base_wallet.deposit)
        )
    _save_portfolio(portfolio)
    return TradeResult(currency_code, amount, rate, base_currency, balance_changes)
