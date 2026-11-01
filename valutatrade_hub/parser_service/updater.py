"""Координация обновления курсов: опрос клиентов, объединение и сохранение."""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import PROJECT_ROOT
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RateMeasurement, RatesStorage

UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CLIENTS_BY_SOURCE: dict[str, type[BaseApiClient]] = {
    "coingecko": CoinGeckoClient,
    "exchangerate": ExchangeRateApiClient,
}

parser_logger = logging.getLogger(PARSER_LOGGER_NAME)


@dataclass(frozen=True)
class SourceResult:
    """Сколько курсов вернул источник и текст ошибки, если он упал."""

    source: str
    rates_count: int
    error: str | None = None


@dataclass(frozen=True)
class UpdateResult:
    """Итог обновления: сколько пар записано и что вернул каждый источник."""

    updated_count: int
    last_refresh: str
    source_results: list[SourceResult]

    @property
    def has_errors(self) -> bool:
        return any(result.error for result in self.source_results)


def _utc_now() -> str:
    return datetime.now(UTC).strftime(UTC_TIMESTAMP_FORMAT)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


class RatesUpdater:
    """Опрашивает все клиенты и сохраняет полученные курсы.

    Ошибка одного клиента логируется и не прерывает обновление:
    сохраняются данные от остальных источников.
    """

    def __init__(
        self,
        clients: list[BaseApiClient],
        storage: RatesStorage,
        config: ParserConfig,
    ) -> None:
        self.clients = clients
        self.storage = storage
        self.config = config

    def _fetch_measurements(self, client: BaseApiClient) -> list[RateMeasurement]:
        rates = client.fetch_rates()
        timestamp = _utc_now()
        request_meta = (
            asdict(client.last_request_meta) if client.last_request_meta else {}
        )
        measurements = []
        for pair_key, rate in rates.items():
            from_currency, to_currency = pair_key.split("_")
            # raw_id есть только у криптовалют: ID монеты в CoinGecko.
            raw_id = self.config.crypto_id_map.get(from_currency)
            meta = {"raw_id": raw_id, **request_meta}
            measurements.append(
                RateMeasurement(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate=rate,
                    timestamp=timestamp,
                    source=client.source_name,
                    meta=meta,
                )
            )
        return measurements

    def run_update(self) -> UpdateResult:
        """Обновить rates.json и дописать историю в exchange_rates.json.

        Raises:
            ApiRequestError: ни один источник не вернул курсы.
        """
        parser_logger.info("Starting rates update...")
        measurements: list[RateMeasurement] = []
        source_results: list[SourceResult] = []
        for client in self.clients:
            try:
                client_measurements = self._fetch_measurements(client)
            except ApiRequestError as error:
                parser_logger.error(
                    "Failed to fetch from %s: %s", client.source_name, error.reason
                )
                # Traceback с исходной причиной (requests, JSON) идёт только
                # в parser.log: консольный обработчик пропускает DEBUG.
                parser_logger.debug(
                    "Failure details for %s", client.source_name, exc_info=True
                )
                source_results.append(SourceResult(client.source_name, 0, error.reason))
                continue
            parser_logger.info(
                "Fetching from %s... OK (%d rates)",
                client.source_name,
                len(client_measurements),
            )
            measurements.extend(client_measurements)
            source_results.append(
                SourceResult(client.source_name, len(client_measurements))
            )

        if not measurements:
            parser_logger.error("Rates update failed: no source returned data")
            raise ApiRequestError("не удалось получить курсы ни из одного источника")

        last_refresh = _utc_now()
        parser_logger.info(
            "Writing %d rates to %s...",
            len(measurements),
            _display_path(self.config.rates_file_path),
        )
        updated_count = self.storage.save_snapshot(measurements, last_refresh)
        history_count = self.storage.append_history(measurements)
        parser_logger.info(
            "Rates update finished: %d pairs updated, %d history records added",
            updated_count,
            history_count,
        )
        return UpdateResult(updated_count, last_refresh, source_results)


def build_updater(source: str | None = None) -> RatesUpdater:
    """Создать RatesUpdater со всеми клиентами или только с указанным источником.

    Raises:
        ValueError: источник не из CLIENTS_BY_SOURCE.
    """
    config = ParserConfig()
    if source is None:
        client_classes = list(CLIENTS_BY_SOURCE.values())
    else:
        normalized_source = source.strip().lower()
        if normalized_source not in CLIENTS_BY_SOURCE:
            available_sources = ", ".join(CLIENTS_BY_SOURCE)
            raise ValueError(
                f"Неизвестный источник '{source}'. Доступны: {available_sources}"
            )
        client_classes = [CLIENTS_BY_SOURCE[normalized_source]]
    clients = [client_class(config) for client_class in client_classes]
    return RatesUpdater(clients, RatesStorage(), config)
