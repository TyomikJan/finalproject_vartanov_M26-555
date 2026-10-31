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

## Проверка кода

```bash
uv run ruff check .
```
