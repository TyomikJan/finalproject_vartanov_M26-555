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

Для фиатных курсов нужен бесплатный ключ [ExchangeRate-API](https://www.exchangerate-api.com/).
Скопируйте `.env.example` в `.env` и впишите ключ (файл `.env` не попадает в git):

```bash
cp .env.example .env
```

Вместо файла можно задать переменную окружения `EXCHANGERATE_API_KEY`.
Криптовалюты берутся из CoinGecko без ключа.

## Команды

```
register --username alice --password 1234
login --username alice --password 1234
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio --base USD
get-rate --from USD --to BTC
update-rates --source coingecko
show-rates --top 2
show-rates --currency EUR --base RUB
```

Поддерживаемые валюты: USD, EUR, GBP, RUB, BTC, ETH, SOL.

## Модель торговли

Используется полная модель:
- при регистрации на USD-кошелёк начисляется стартовый баланс
  (`initial_balance` в настройках, по умолчанию 10 000 USD);
- `buy` списывает стоимость покупки с USD-кошелька, при нехватке средств
  выводится ошибка «Недостаточно средств»;
- `sell` зачисляет выручку на USD-кошелёк;
- сделки USD за USD не поддерживаются.

Сессия: новый `login` заменяет текущего пользователя.

## Parser Service и кеш курсов

Parser Service получает курсы из CoinGecko и ExchangeRate-API и сохраняет:
- `data/rates.json` — последний курс каждой пары к USD, его читает основное приложение;
- `data/exchange_rates.json` — история всех замеров.

Курс из кеша считается актуальным 5 минут после обновления (`rates_ttl_seconds`
в настройках). Пока он актуален, приложение берёт его из `rates.json` и не обращается
к API. Если курс старше 5 минут или его ещё нет, команды `get-rate`, `buy`, `sell`
и `show-portfolio` сначала сами обновляют кеш и только потом выполняются.

Обновить кеш можно тремя способами:
- автоматически — как описано выше, при обращении к устаревшему курсу;
- вручную — командой `update-rates` внутри приложения;
- по расписанию — планировщиком в отдельном терминале:

```bash
uv run parser
```

## Структура

```
valutatrade_hub/
├── core/            # модели, валюты, исключения, бизнес-логика
├── infra/           # SettingsLoader и DatabaseManager (синглтоны)
├── parser_service/  # API-клиенты, обновление и хранение курсов, планировщик
├── cli/             # командный интерфейс
├── logging_config.py
└── decorators.py    # @log_action
data/                # users.json, portfolios.json, rates.json, exchange_rates.json
```

## Настройки и логи

Конфигурация задаётся в `pyproject.toml`, секция `[tool.valutatrade]`:
пути к данным, время жизни кеша курсов (`rates_ttl_seconds`, по умолчанию 5 минут),
базовая валюта, стартовый баланс и параметры логов.

Операции register, login, buy и sell записываются в `logs/actions.log`,
работа Parser Service — в `logs/parser.log` (ротация по размеру 1 МБ, 5 архивных файлов).

## Проверка кода

```bash
uv run ruff check .
```
