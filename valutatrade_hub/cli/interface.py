"""Командный интерфейс приложения: разбор команд и вывод результатов."""

import shlex
from collections.abc import Callable

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.models import BASE_CURRENCY, User
from valutatrade_hub.core.usecases import NotLoggedInError, RateUnavailableError

PROMPT = "> "
EXIT_COMMANDS = {"exit", "quit"}

COMMANDS_HELP = [
    ("register --username <str> --password <str>", "Регистрация"),
    ("login --username <str> --password <str>", "Вход в систему"),
    ("show-portfolio [--base <str>]", "Портфель и итоговая стоимость"),
    ("buy --currency <str> --amount <float>", "Купить валюту"),
    ("sell --currency <str> --amount <float>", "Продать валюту"),
    ("get-rate --from <str> --to <str>", "Курс валюты"),
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


def format_rate(rate: float) -> str:
    """Отформатировать курс: мелкие значения показываются с большей точностью."""
    return f"{rate:.2f}" if rate >= 1 else f"{rate:.8f}"


def format_trade(title: str, value_label: str, trade: usecases.TradeResult) -> str:
    return "\n".join(
        [
            f"{title}: {trade.amount:.4f} {trade.currency_code} по курсу "
            f"{format_rate(trade.rate)} {trade.base_currency}/{trade.currency_code}",
            "Изменения в портфеле:",
            f"- {trade.currency_code}: было {trade.balance_before:.4f} "
            f"→ стало {trade.balance_after:.4f}",
            f"{value_label}: {trade.estimated_value:,.2f} {trade.base_currency}",
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
            "help": self.show_help,
        }

    def register(self, options: dict[str, str]) -> str:
        user = usecases.register(
            require_option(options, "username"), require_option(options, "password")
        )
        return (
            f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
            f"Войдите: login --username {user.username} --password ****"
        )

    def login(self, options: dict[str, str]) -> str:
        self.current_user = usecases.login(
            require_option(options, "username"), require_option(options, "password")
        )
        return f"Вы вошли как '{self.current_user.username}'"

    def show_portfolio(self, options: dict[str, str]) -> str:
        report = usecases.show_portfolio(
            self.current_user, options.get("base", BASE_CURRENCY)
        )
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
                    f"{wallet.balance:.4f}",
                    f"{wallet.value_in_base:,.2f}",
                ]
            )
        total_line = f"ИТОГО: {report.total_value:,.2f} {report.base_currency}"
        return f"{header}\n{table}\n{total_line}"

    def buy(self, options: dict[str, str]) -> str:
        trade = usecases.buy(
            self.current_user,
            require_option(options, "currency"),
            require_option(options, "amount"),
        )
        return format_trade("Покупка выполнена", "Оценочная стоимость покупки", trade)

    def sell(self, options: dict[str, str]) -> str:
        trade = usecases.sell(
            self.current_user,
            require_option(options, "currency"),
            require_option(options, "amount"),
        )
        return format_trade("Продажа выполнена", "Оценочная выручка", trade)

    def get_rate(self, options: dict[str, str]) -> str:
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

    def show_help(self, options: dict[str, str]) -> str:
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
        except (ValueError, NotLoggedInError, RateUnavailableError) as error:
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
    CommandLineInterface().run()
