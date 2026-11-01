"""Хранение курсов: снимок rates.json и история замеров exchange_rates.json.

Обе записи идут через DatabaseManager, то есть атомарно (временный файл → rename).
"""

from dataclasses import dataclass
from datetime import datetime

from valutatrade_hub.infra.database import DatabaseManager


@dataclass(frozen=True)
class RateMeasurement:
    """Один успешно полученный курс пары с источником и временем замера."""

    from_currency: str
    to_currency: str
    rate: float
    timestamp: str
    source: str
    meta: dict

    @property
    def pair_key(self) -> str:
        return f"{self.from_currency}_{self.to_currency}"

    @property
    def record_id(self) -> str:
        return f"{self.pair_key}_{self.timestamp}"


def _parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def normalize_rates_cache(raw_cache: dict) -> dict:
    """Привести содержимое rates.json к виду {"pairs": {...}, "last_refresh": ...}.

    Файл старого формата (пары на верхнем уровне без "pairs") считается пустым.
    """
    return {
        "pairs": dict(raw_cache.get("pairs", {})),
        "last_refresh": raw_cache.get("last_refresh"),
    }


class RatesStorage:
    """Операции чтения и записи кеша курсов и их истории."""

    def __init__(self) -> None:
        self.database = DatabaseManager()

    def load_cache(self) -> dict:
        """Вернуть текущий снимок курсов из rates.json."""
        return normalize_rates_cache(self.database.read("rates"))

    def save_snapshot(
        self, measurements: list[RateMeasurement], refreshed_at: str
    ) -> int:
        """Обновить rates.json и вернуть число пар, которые действительно изменились.

        Для каждой пары хранится один последний срез; новый замер заменяет
        старый, только если его updated_at свежее.
        """
        cache = self.load_cache()
        updated_count = 0
        for measurement in measurements:
            current_entry = cache["pairs"].get(measurement.pair_key)
            is_newer = current_entry is None or _parse_timestamp(
                measurement.timestamp
            ) > _parse_timestamp(current_entry["updated_at"])
            if is_newer:
                cache["pairs"][measurement.pair_key] = {
                    "rate": measurement.rate,
                    "updated_at": measurement.timestamp,
                    "source": measurement.source,
                }
                updated_count += 1
        cache["last_refresh"] = refreshed_at
        self.database.write("rates", cache)
        return updated_count

    def append_history(self, measurements: list[RateMeasurement]) -> int:
        """Дописать замеры в exchange_rates.json, пропуская уже записанные id."""
        records = self.database.read("exchange_rates")
        known_ids = {record["id"] for record in records}
        added_count = 0
        for measurement in measurements:
            if measurement.record_id in known_ids:
                continue
            records.append(
                {
                    "id": measurement.record_id,
                    "from_currency": measurement.from_currency,
                    "to_currency": measurement.to_currency,
                    "rate": measurement.rate,
                    "timestamp": measurement.timestamp,
                    "source": measurement.source,
                    "meta": measurement.meta,
                }
            )
            known_ids.add(measurement.record_id)
            added_count += 1
        self.database.write("exchange_rates", records)
        return added_count
