# ValutaTrade Hub

Консольное приложение для симуляции торговли валютами.

## Установка и запуск

Нужны Python 3.12+ и [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run project
```

## Команды

```
register --username alice --password 1234
login --username alice --password 1234
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio --base USD
get-rate --from USD --to BTC
```

Выручка от продажи зачисляется на USD-кошелёк.
Поддерживаемые валюты: USD, EUR, RUB, BTC, ETH.

## Настройки и логи

Конфигурация задаётся в `pyproject.toml`, секция `[tool.valutatrade]`:
пути к данным, время жизни кеша курсов (`rates_ttl_seconds`, по умолчанию 5 минут),
базовая валюта и параметры логов.

Операции register, login, buy и sell записываются в `logs/actions.log`
(ротация по размеру 1 МБ, 5 архивных файлов).

## Проверка кода

```bash
uv run ruff check .
```
