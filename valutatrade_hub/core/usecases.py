"""Бизнес-логика приложения: пользователи, портфели, сделки и курсы валют.

Конфигурация берётся из синглтона SettingsLoader (базовая валюта, TTL курсов),
данные читаются и пишутся через синглтон DatabaseManager. Курсы берутся из
кеша rates.json, который обновляет Parser Service. Операции register, login,
buy и sell логируются декоратором @log_action.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    InvalidPasswordError,
    NotLoggedInError,
    RateNotFoundError,
    RatesCacheEmptyError,
    UsernameTakenError,
    UserNotFoundError,
    WalletNotFoundError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import parse_amount, validate_currency_code
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.config import BASE_FIAT_CURRENCY, CRYPTO_CURRENCIES
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import UpdateResult, build_updater

settings = SettingsLoader()
database = DatabaseManager()
rates_storage = RatesStorage()


# Dataclass для обмена данными с модулем CLI


@dataclass(frozen=True)
class RateInfo:
    """Курс from_code → to_code и время его обновления (UTC)."""

    from_code: str
    to_code: str
    rate: float
    updated_at: datetime

    @property
    def inverse_rate(self) -> float:
        return 1 / self.rate


@dataclass(frozen=True)
class CachedRate:
    """Курс пары из кеша, например BTC_USD, и время его обновления."""

    pair_key: str
    rate: float
    updated_at: str


@dataclass(frozen=True)
class CachedRates:
    """Курсы из кеша и время последнего обновления всего кеша."""

    last_refresh: str | None
    rates: list[CachedRate]


@dataclass(frozen=True)
class WalletValue:
    """Баланс кошелька и его стоимость в базовой валюте."""

    currency_code: str
    balance: float
    value_in_base: float


@dataclass(frozen=True)
class PortfolioReport:
    """Состав портфеля и итоговая стоимость в базовой валюте."""

    username: str
    base_currency: str
    wallets: list[WalletValue]
    total_value: float


@dataclass(frozen=True)
class BalanceChange:
    """Баланс кошелька до и после сделки."""

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


def _find_user_by_id(user_id: int) -> User | None:
    return next((user for user in _load_users() if user.user_id == user_id), None)


def _load_portfolio(user: User) -> Portfolio:
    for record in database.read("portfolios"):
        if record["user_id"] == user.user_id:
            return Portfolio.from_dict(record, user)
    return Portfolio(user.user_id, user=user)


def _save_portfolio(portfolio: Portfolio) -> None:
    records = [
        record
        for record in database.read("portfolios")
        if record["user_id"] != portfolio.user_id
    ]
    records.append(portfolio.to_dict())
    database.write("portfolios", records)


def _require_login(user_id: int | None) -> User:
    """Вернуть пользователя текущей сессии или сообщить, что вход не выполнен."""
    if user_id is None:
        raise NotLoggedInError()
    user = _find_user_by_id(user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return user


@log_action("REGISTER")
def register(username: str, password: str) -> User:
    """Зарегистрировать пользователя и создать ему портфель.

    На кошелёк базовой валюты начисляется стартовый баланс
    initial_balance из настроек.

    Raises:
        UsernameTakenError: имя уже занято.
    """
    records = database.read("users")
    if any(record["username"] == username.strip() for record in records):
        raise UsernameTakenError(username)
    next_user_id = max((record["user_id"] for record in records), default=0) + 1
    user = User.create(user_id=next_user_id, username=username, password=password)
    records.append(user.to_dict())
    database.write("users", records)

    portfolio = Portfolio(user.user_id, user=user)
    initial_balance = settings.get("initial_balance")
    if initial_balance > 0:
        portfolio.add_currency(_base_currency()).deposit(initial_balance)
    _save_portfolio(portfolio)
    return user


@log_action("LOGIN")
def login(username: str, password: str) -> User:
    """Найти пользователя и проверить его пароль.

    Raises:
        UserNotFoundError: пользователя с таким именем нет.
        InvalidPasswordError: пароль не подошёл.
    """
    user = _find_user(username)
    if user is None:
        raise UserNotFoundError(username)
    if not user.verify_password(password):
        raise InvalidPasswordError()
    return user


def _read_fresh_rate(from_code: str, to_code: str) -> RateInfo | None:
    """Кросс-курс через USD из rates.json или None, если данных нет или они устарели.

    В кеше хранятся только пары к USD, поэтому курс from→to считается как
    (from→USD) / (to→USD), а время обновления — по более старой из двух пар.
    """
    pairs = rates_storage.load_cache()["pairs"]
    rates_to_usd = {BASE_FIAT_CURRENCY: 1.0}
    update_times = []
    for code in (from_code, to_code):
        if code == BASE_FIAT_CURRENCY:
            continue
        entry = pairs.get(f"{code}_{BASE_FIAT_CURRENCY}")
        if entry is None:
            return None
        rates_to_usd[code] = entry["rate"]
        update_times.append(datetime.fromisoformat(entry["updated_at"]))

    now = datetime.now(UTC)
    updated_at = min(update_times, default=now)
    if now - updated_at >= timedelta(seconds=settings.get("rates_ttl_seconds")):
        return None
    rate = rates_to_usd[from_code] / rates_to_usd[to_code]
    return RateInfo(from_code, to_code, rate, updated_at)


def get_rate(from_code: str, to_code: str) -> RateInfo:
    """Вернуть курс from_code → to_code и время его обновления.

    Курс берётся из кеша rates.json, который ведёт Parser Service. Если
    нужной пары нет или она старше rates_ttl_seconds, запускается
    обновление кеша, после чего курс читается повторно.

    Raises:
        CurrencyNotFoundError: один из кодов не поддерживается.
        ApiRequestError: кеш устарел, а обновить его не удалось.
    """
    from_code = get_currency(from_code).code
    to_code = get_currency(to_code).code
    if from_code == to_code:
        return RateInfo(from_code, to_code, 1.0, datetime.now(UTC))

    rate_info = _read_fresh_rate(from_code, to_code)
    if rate_info is None:
        build_updater().run_update()
        rate_info = _read_fresh_rate(from_code, to_code)
    if rate_info is None:
        raise ApiRequestError(f"курс {from_code}→{to_code} недоступен")
    return rate_info


def update_rates(source: str | None = None) -> UpdateResult:
    """Обновить кеш курсов из всех источников или только из source."""
    return build_updater(source).run_update()


def _parse_top(top: int | str) -> int:
    error_message = "'top' должен быть положительным целым числом"
    try:
        parsed_top = int(top)
    except (TypeError, ValueError) as error:
        raise ValueError(error_message) from error
    if parsed_top <= 0:
        raise ValueError(error_message)
    return parsed_top


def show_rates(
    currency_code: str | None = None,
    top: int | str | None = None,
    base_currency: str | None = None,
) -> CachedRates:
    """Курсы из локального кеша с фильтрами.

    currency_code — только одна валюта, top — N самых дорогих криптовалют,
    base_currency — пересчитать курсы к другой базе (по умолчанию USD).

    Raises:
        RatesCacheEmptyError: кеш пуст или не найден.
        RateNotFoundError: в кеше нет курса для запрошенной валюты.
    """
    cache = rates_storage.load_cache()
    if not cache["pairs"]:
        raise RatesCacheEmptyError()

    # Код валюты → запись кеша {"rate": курс к USD, "updated_at": ...}.
    entries = {
        pair_key.split("_")[0]: entry for pair_key, entry in cache["pairs"].items()
    }
    target_base = validate_currency_code(base_currency or BASE_FIAT_CURRENCY)
    if target_base == BASE_FIAT_CURRENCY:
        base_rate = 1.0
    elif target_base in entries:
        base_rate = entries[target_base]["rate"]
    else:
        raise RateNotFoundError(target_base)

    rates = {
        code: CachedRate(
            f"{code}_{target_base}", entry["rate"] / base_rate, entry["updated_at"]
        )
        for code, entry in entries.items()
        if code != target_base
    }
    if target_base != BASE_FIAT_CURRENCY:
        rates[BASE_FIAT_CURRENCY] = CachedRate(
            f"{BASE_FIAT_CURRENCY}_{target_base}",
            1 / base_rate,
            entries[target_base]["updated_at"],
        )

    if currency_code is not None:
        code = validate_currency_code(currency_code)
        if code not in rates:
            raise RateNotFoundError(code)
        rates = {code: rates[code]}

    if top is not None:
        crypto_rates = [rates[code] for code in rates if code in CRYPTO_CURRENCIES]
        crypto_rates.sort(key=lambda cached_rate: cached_rate.rate, reverse=True)
        selected_rates = crypto_rates[: _parse_top(top)]
    else:
        selected_rates = [rates[code] for code in sorted(rates)]

    return CachedRates(last_refresh=cache["last_refresh"], rates=selected_rates)


def show_portfolio(
    user_id: int | None, base_currency: str | None = None
) -> PortfolioReport:
    """Собрать балансы кошельков и их стоимость в базовой валюте.

    Курсы к USD берутся из кеша и передаются в Portfolio.get_total_value.
    """
    user = _require_login(user_id)
    base_currency = get_currency(base_currency or _base_currency()).code
    portfolio = _load_portfolio(user)
    wallets = portfolio.wallets
    rates_to_usd = {
        currency_code: get_rate(currency_code, BASE_FIAT_CURRENCY).rate
        for currency_code in {*wallets, base_currency}
    }
    wallet_values = [
        WalletValue(
            currency_code=currency_code,
            balance=wallet.balance,
            value_in_base=wallet.balance
            * rates_to_usd[currency_code]
            / rates_to_usd[base_currency],
        )
        for currency_code, wallet in wallets.items()
    ]
    total_value = portfolio.get_total_value(base_currency, rates=rates_to_usd)
    return PortfolioReport(user.username, base_currency, wallet_values, total_value)


def _get_or_create_wallet(portfolio: Portfolio, currency_code: str) -> Wallet:
    return portfolio.get_wallet(currency_code) or portfolio.add_currency(currency_code)


def _reject_base_currency_trade(currency_code: str, base_currency: str) -> None:
    if currency_code == base_currency:
        raise ValueError(
            f"Сделки {base_currency} за {base_currency} не поддерживаются: "
            f"покупка и продажа идут за {base_currency}"
        )


@log_action("BUY", verbose=True)
def buy(user_id: int | None, currency_code: str, amount: float | str) -> TradeResult:
    """Купить amount единиц валюты за базовую валюту.

    Стоимость amount * rate списывается с кошелька базовой валюты,
    кошелёк покупаемой валюты создаётся при первой покупке. Портфель
    сохраняется, только если все операции прошли успешно.

    Raises:
        InsufficientFundsError: в базовой валюте не хватает средств.
    """
    user = _require_login(user_id)
    currency_code = get_currency(currency_code).code
    amount = parse_amount(amount)
    base_currency = _base_currency()
    _reject_base_currency_trade(currency_code, base_currency)
    rate = get_rate(currency_code, base_currency).rate

    portfolio = _load_portfolio(user)
    base_wallet = _get_or_create_wallet(portfolio, base_currency)
    base_balance_before = base_wallet.balance
    base_wallet.withdraw(amount * rate)
    wallet = _get_or_create_wallet(portfolio, currency_code)
    balance_before = wallet.balance
    wallet.deposit(amount)
    _save_portfolio(portfolio)

    balance_changes = [
        BalanceChange(currency_code, balance_before, wallet.balance),
        BalanceChange(base_currency, base_balance_before, base_wallet.balance),
    ]
    return TradeResult(currency_code, amount, rate, base_currency, balance_changes)


@log_action("SELL", verbose=True)
def sell(user_id: int | None, currency_code: str, amount: float | str) -> TradeResult:
    """Продать amount единиц валюты; выручка зачисляется на кошелёк базовой валюты.

    Raises:
        WalletNotFoundError: кошелька в этой валюте нет.
        InsufficientFundsError: на кошельке меньше, чем amount.
    """
    user = _require_login(user_id)
    currency_code = get_currency(currency_code).code
    amount = parse_amount(amount)
    base_currency = _base_currency()
    _reject_base_currency_trade(currency_code, base_currency)

    portfolio = _load_portfolio(user)
    wallet = portfolio.get_wallet(currency_code)
    if wallet is None:
        raise WalletNotFoundError(currency_code)
    rate = get_rate(currency_code, base_currency).rate
    base_wallet = _get_or_create_wallet(portfolio, base_currency)
    balance_before = wallet.balance
    base_balance_before = base_wallet.balance
    wallet.withdraw(amount)
    base_wallet.deposit(amount * rate)
    _save_portfolio(portfolio)

    balance_changes = [
        BalanceChange(currency_code, balance_before, wallet.balance),
        BalanceChange(base_currency, base_balance_before, base_wallet.balance),
    ]
    return TradeResult(currency_code, amount, rate, base_currency, balance_changes)
