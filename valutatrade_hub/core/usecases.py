"""Бизнес-логика приложения: пользователи, портфели, сделки и курсы валют."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from valutatrade_hub.core.models import (
    BASE_CURRENCY,
    EXCHANGE_RATES_TO_USD,
    Portfolio,
    User,
)
from valutatrade_hub.core.utils import (
    PORTFOLIOS_FILE,
    RATES_FILE,
    USERS_FILE,
    load_json,
    parse_amount,
    save_json,
    validate_currency_code,
)

RATES_TTL = timedelta(minutes=5)
RATES_SOURCE = "ParserServiceStub"


class NotLoggedInError(Exception):
    """Команда требует входа в систему."""

    def __init__(self) -> None:
        super().__init__("Сначала выполните login")


class RateUnavailableError(Exception):
    """Курс валютной пары не удалось получить ни из кеша, ни из источника."""

    def __init__(self, from_code: str, to_code: str) -> None:
        self.from_code = from_code
        self.to_code = to_code
        super().__init__(
            f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже."
        )


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
class TradeResult:
    currency_code: str
    amount: float
    rate: float
    base_currency: str
    balance_before: float
    balance_after: float

    @property
    def estimated_value(self) -> float:
        return self.amount * self.rate


def _load_users() -> list[User]:
    return [User.from_dict(record) for record in load_json(USERS_FILE, [])]


def _save_users(users: list[User]) -> None:
    save_json(USERS_FILE, [user.to_dict() for user in users])


def _find_user(username: str) -> User | None:
    return next((user for user in _load_users() if user.username == username), None)


def _load_portfolio(user: User) -> Portfolio:
    for record in load_json(PORTFOLIOS_FILE, []):
        if record["user_id"] == user.user_id:
            return Portfolio.from_dict(record, user)
    return Portfolio(user)


def _save_portfolio(portfolio: Portfolio) -> None:
    records = [
        record
        for record in load_json(PORTFOLIOS_FILE, [])
        if record["user_id"] != portfolio.user_id
    ]
    records.append(portfolio.to_dict())
    save_json(PORTFOLIOS_FILE, records)


def _require_login(user: User | None) -> User:
    if user is None:
        raise NotLoggedInError()
    return user


def register(username: str, password: str) -> User:
    """Зарегистрировать пользователя и создать ему пустой портфель."""
    users = _load_users()
    if any(existing.username == username.strip() for existing in users):
        raise ValueError(f"Имя пользователя '{username}' уже занято")

    next_user_id = max((existing.user_id for existing in users), default=0) + 1
    user = User.create(user_id=next_user_id, username=username, password=password)
    users.append(user)
    _save_users(users)
    _save_portfolio(Portfolio(user))
    return user


def login(username: str, password: str) -> User:
    """Найти пользователя и проверить его пароль."""
    user = _find_user(username)
    if user is None:
        raise ValueError(f"Пользователь '{username}' не найден")
    if not user.verify_password(password):
        raise ValueError("Неверный пароль")
    return user


def _fetch_rate_from_source(from_code: str, to_code: str) -> float | None:
    """Заглушка Parser Service: кросс-курс через фиксированные курсы к USD."""
    if from_code not in EXCHANGE_RATES_TO_USD or to_code not in EXCHANGE_RATES_TO_USD:
        return None
    return EXCHANGE_RATES_TO_USD[from_code] / EXCHANGE_RATES_TO_USD[to_code]


def get_rate(from_code: str, to_code: str) -> RateInfo:
    """Вернуть курс from_code→to_code.

    Свежий курс (моложе RATES_TTL) берётся из кеша rates.json, иначе
    запрашивается у источника и кеш обновляется. Если источник недоступен,
    используется устаревшее значение из кеша, когда оно есть.
    """
    from_code = validate_currency_code(from_code)
    to_code = validate_currency_code(to_code)
    now = datetime.now()
    if from_code == to_code:
        return RateInfo(from_code, to_code, 1.0, now)

    cache = load_json(RATES_FILE, {})
    pair_key = f"{from_code}_{to_code}"
    cached_entry = cache.get(pair_key)
    cached_rate = None
    if cached_entry:
        cached_rate = RateInfo(
            from_code,
            to_code,
            cached_entry["rate"],
            datetime.fromisoformat(cached_entry["updated_at"]),
        )
        if now - cached_rate.updated_at < RATES_TTL:
            return cached_rate

    fresh_rate = _fetch_rate_from_source(from_code, to_code)
    if fresh_rate is None:
        if cached_rate is not None:
            return cached_rate
        raise RateUnavailableError(from_code, to_code)

    cache[pair_key] = {"rate": fresh_rate, "updated_at": now.isoformat()}
    cache["source"] = RATES_SOURCE
    cache["last_refresh"] = now.isoformat()
    save_json(RATES_FILE, cache)
    return RateInfo(from_code, to_code, fresh_rate, now)


def show_portfolio(
    user: User | None, base_currency: str = BASE_CURRENCY
) -> PortfolioReport:
    """Собрать балансы кошельков и их стоимость в базовой валюте."""
    user = _require_login(user)
    base_currency = validate_currency_code(base_currency)
    try:
        get_rate(BASE_CURRENCY, base_currency)
    except RateUnavailableError as error:
        raise ValueError(f"Неизвестная базовая валюта '{base_currency}'") from error

    wallet_values = [
        WalletValue(
            currency_code=currency_code,
            balance=wallet.balance,
            value_in_base=wallet.balance * get_rate(currency_code, base_currency).rate,
        )
        for currency_code, wallet in _load_portfolio(user).wallets.items()
    ]
    return PortfolioReport(user.username, base_currency, wallet_values)


def _get_trade_rate(currency_code: str) -> float:
    try:
        return get_rate(currency_code, BASE_CURRENCY).rate
    except RateUnavailableError as error:
        raise ValueError(
            f"Не удалось получить курс для {currency_code}→{BASE_CURRENCY}"
        ) from error


def buy(user: User | None, currency_code: str, amount: float | str) -> TradeResult:
    """Купить amount единиц валюты; кошелёк создаётся при первой покупке."""
    user = _require_login(user)
    currency_code = validate_currency_code(currency_code)
    amount = parse_amount(amount)
    rate = _get_trade_rate(currency_code)

    portfolio = _load_portfolio(user)
    wallet = portfolio.get_wallet(currency_code) or portfolio.add_currency(
        currency_code
    )
    balance_before = wallet.balance
    wallet.deposit(amount)
    _save_portfolio(portfolio)
    return TradeResult(
        currency_code, amount, rate, BASE_CURRENCY, balance_before, wallet.balance
    )


def sell(user: User | None, currency_code: str, amount: float | str) -> TradeResult:
    """Продать amount единиц валюты с существующего кошелька."""
    user = _require_login(user)
    currency_code = validate_currency_code(currency_code)
    amount = parse_amount(amount)

    portfolio = _load_portfolio(user)
    wallet = portfolio.get_wallet(currency_code)
    if wallet is None:
        raise ValueError(
            f"У вас нет кошелька '{currency_code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        )
    rate = _get_trade_rate(currency_code)
    balance_before = wallet.balance
    wallet.withdraw(amount)
    _save_portfolio(portfolio)
    return TradeResult(
        currency_code, amount, rate, BASE_CURRENCY, balance_before, wallet.balance
    )
