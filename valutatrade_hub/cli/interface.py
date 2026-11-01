"""Командный интерфейс приложения: разбор команд и вывод результатов."""

import shlex
from collections.abc import Callable
from pathlib import Path

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import get_currency, get_supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    ValutaTradeError,
)
from valutatrade_hub.core.models import User
from valutatrade_hub.core.utils import format_rate
from valutatrade_hub.infra.settings import PROJECT_ROOT, SettingsLoader
from valutatrade_hub.logging_config import parser_console_output, setup_logging

PROMPT = "> "
EXIT_COMMANDS = {"exit", "quit"}

COMMANDS_HELP = [
    ("register --username <str> --password <str>", "Регистрация"),
    ("login --username <str> --password <str>", "Вход в систему"),
    ("show-portfolio [--base <str>]", "Портфель и итоговая стоимость"),
    ("buy --currency <str> --amount <float>", "Купить валюту"),
    ("sell --currency <str> --amount <float>", "Продать валюту"),
    ("get-rate --from <str> --to <str>", "Курс валюты"),
    ("update-rates [--source coingecko|exchangerate]", "Обновить курсы из API"),
    (
        "show-rates [--currency <str>] [--top <int>] [--base <str>]",
        "Курсы из локального кеша",
    ),
    ("help", "Список команд"),
    ("exit", "Выход"),
]


def parse_options(arguments: list[str]) -> dict[str, str]:
    """Разобрать аргументы вида --name value в словарь."""
    options: dict[str, str] = {}
    argument_iterator = iter(arguments)
    for argument in argument_iterator:
        if not argument.startswith("--") or len(argument) == 2:
            raise ValueError(f"Неожиданный аргумент '{argument}'")
        option_name = argument[2:]
        option_value = next(argument_iterator, None)
        if option_value is None or option_value.startswith("--"):
            raise ValueError(f"Не указано значение для --{option_name}")
        options[option_name] = option_value
    return options


def require_option(options: dict[str, str], name: str) -> str:
    """Вернуть обязательный аргумент или сообщить, что он не указан."""
    if name not in options:
        raise ValueError(f"Не указан обязательный аргумент --{name}")
    return options[name]


def format_balance(balance: float) -> str:
    """Отформатировать баланс: дробные остатки показываются с 4 знаками."""
    return f"{balance:.2f}" if balance >= 1 else f"{balance:.4f}"


def format_trade(title: str, value_label: str, trade: usecases.TradeResult) -> str:
    """Собрать отчёт о сделке: курс, изменения балансов и сумму в USD."""
    change_lines = [
        f"- {change.currency_code}: было {change.balance_before:.4f} "
        f"→ стало {change.balance_after:.4f}"
        for change in trade.balance_changes
    ]
    return "\n".join(
        [
            f"{title}: {trade.amount:.4f} {trade.currency_code} по курсу "
            f"{format_rate(trade.rate)} {trade.base_currency}/{trade.currency_code}",
            "Изменения в портфеле:",
            *change_lines,
            f"{value_label}: {trade.estimated_value:,.2f} {trade.base_currency}",
            f"Валюта: {get_currency(trade.currency_code).get_display_info()}",
        ]
    )


class CommandLineInterface:
    """Интерактивная оболочка, хранящая текущую сессию пользователя."""

    def __init__(self) -> None:
        self.current_user: User | None = None
        self.handlers: dict[str, Callable[[dict[str, str]], str]] = {
            "register": self.register,
            "login": self.login,
            "show-portfolio": self.show_portfolio,
            "buy": self.buy,
            "sell": self.sell,
            "get-rate": self.get_rate,
            "update-rates": self.update_rates,
            "show-rates": self.show_rates,
            "help": self.show_help,
        }

    @property
    def current_user_id(self) -> int | None:
        """id пользователя текущей сессии или None, если вход не выполнен."""
        return self.current_user.user_id if self.current_user else None

    def register(self, options: dict[str, str]) -> str:
        """Зарегистрировать пользователя (--username, --password)."""
        user = usecases.register(
            require_option(options, "username"), require_option(options, "password")
        )
        return (
            f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
            f"Войдите: login --username {user.username} --password ****"
        )

    def login(self, options: dict[str, str]) -> str:
        """Войти и запомнить пользователя; новый вход заменяет текущую сессию."""
        self.current_user = usecases.login(
            require_option(options, "username"), require_option(options, "password")
        )
        return f"Вы вошли как '{self.current_user.username}'"

    def show_portfolio(self, options: dict[str, str]) -> str:
        """Показать кошельки и итоговую стоимость таблицей."""
        report = usecases.show_portfolio(self.current_user_id, options.get("base"))
        header = (
            f"Портфель пользователя '{report.username}' (база: {report.base_currency}):"
        )
        if not report.wallets:
            return f"{header}\nКошельков пока нет. Купите валюту командой buy."

        table = PrettyTable(["Валюта", "Баланс", f"Стоимость, {report.base_currency}"])
        table.align = "r"
        for wallet in report.wallets:
            table.add_row(
                [
                    wallet.currency_code,
                    format_balance(wallet.balance),
                    f"{wallet.value_in_base:,.2f}",
                ]
            )
        total_line = f"ИТОГО: {report.total_value:,.2f} {report.base_currency}"
        return f"{header}\n{table}\n{total_line}"

    def buy(self, options: dict[str, str]) -> str:
        """Купить валюту (--currency, --amount) и показать изменения."""
        trade = usecases.buy(
            self.current_user_id,
            require_option(options, "currency"),
            require_option(options, "amount"),
        )
        return format_trade("Покупка выполнена", "Оценочная стоимость покупки", trade)

    def sell(self, options: dict[str, str]) -> str:
        """Продать валюту (--currency, --amount) и показать изменения."""
        trade = usecases.sell(
            self.current_user_id,
            require_option(options, "currency"),
            require_option(options, "amount"),
        )
        return format_trade("Продажа выполнена", "Оценочная выручка", trade)

    def get_rate(self, options: dict[str, str]) -> str:
        """Показать прямой и обратный курс (--from, --to)."""
        rate_info = usecases.get_rate(
            require_option(options, "from"), require_option(options, "to")
        )
        updated_at = rate_info.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"Курс {rate_info.from_code}→{rate_info.to_code}: "
            f"{format_rate(rate_info.rate)} (обновлено: {updated_at})\n"
            f"Обратный курс {rate_info.to_code}→{rate_info.from_code}: "
            f"{format_rate(rate_info.inverse_rate)}"
        )

    def update_rates(self, options: dict[str, str]) -> str:
        """Запустить Parser Service и сообщить итог обновления.

        Только здесь логи парсера дублируются в консоль; при get-rate,
        buy и sell обновление кеша пишет их лишь в parser.log.
        """
        with parser_console_output():
            result = usecases.update_rates(options.get("source"))
        if result.has_errors:
            parser_log_file = Path(SettingsLoader().get("parser_log_file"))
            return (
                "Update completed with errors. "
                f"Check {parser_log_file.relative_to(PROJECT_ROOT)} for details."
            )
        total_rates = sum(source.rates_count for source in result.source_results)
        return (
            f"Update successful. Total rates updated: {total_rates}. "
            f"Last refresh: {result.last_refresh}"
        )

    def show_rates(self, options: dict[str, str]) -> str:
        """Показать курсы из кеша с фильтрами --currency, --top и --base."""
        cached_rates = usecases.show_rates(
            options.get("currency"), options.get("top"), options.get("base")
        )
        table = PrettyTable(["Пара", "Курс", "Обновлено (UTC)"])
        table.align = "r"
        table.align["Пара"] = "l"
        for cached_rate in cached_rates.rates:
            table.add_row(
                [
                    cached_rate.pair_key,
                    format_rate(cached_rate.rate),
                    cached_rate.updated_at,
                ]
            )
        header = f"Rates from cache (updated at {cached_rates.last_refresh}):"
        return f"{header}\n{table}"

    def show_help(self, options: dict[str, str]) -> str:
        """Показать таблицу доступных команд."""
        table = PrettyTable(["Команда", "Описание"])
        table.align = "l"
        table.add_rows(COMMANDS_HELP)
        return str(table)

    def execute(self, command_line: str) -> str:
        """Выполнить одну строку ввода и вернуть текст ответа."""
        try:
            tokens = shlex.split(command_line)
        except ValueError as error:
            return f"Ошибка разбора команды: {error}"
        if not tokens:
            return ""

        command_name, *arguments = tokens
        handler = self.handlers.get(command_name)
        if handler is None:
            return f"Неизвестная команда '{command_name}'. Введите help."
        try:
            return handler(parse_options(arguments))
        except InsufficientFundsError as error:
            return str(error)
        except CurrencyNotFoundError as error:
            supported_codes = ", ".join(get_supported_codes())
            return (
                f"{error}\nПоддерживаемые валюты: {supported_codes}. "
                "Курс можно проверить командой get-rate --from <код> --to <код>."
            )
        except ApiRequestError as error:
            return f"{error}\nПовторите попытку позже или проверьте подключение к сети."
        except (ValutaTradeError, ValueError) as error:
            return str(error)

    def run(self) -> None:
        """Запустить цикл чтения команд до exit или Ctrl+D."""
        print("ValutaTrade Hub. Введите help для списка команд.")
        while True:
            try:
                command_line = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if command_line in EXIT_COMMANDS:
                break
            response = self.execute(command_line)
            if response:
                print(response)


def main() -> None:
    """Точка входа CLI."""
    setup_logging()
    CommandLineInterface().run()
