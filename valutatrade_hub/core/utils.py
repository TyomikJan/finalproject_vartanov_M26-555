"""Вспомогательные функции: хеширование паролей и работа с JSON-файлами."""

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
USERS_FILE = DATA_DIR / "users.json"
PORTFOLIOS_FILE = DATA_DIR / "portfolios.json"
RATES_FILE = DATA_DIR / "rates.json"


def generate_salt(length_bytes: int = 8) -> str:
    """Сгенерировать случайную соль в виде hex-строки."""
    return secrets.token_hex(length_bytes)


def hash_password(password: str, salt: str) -> str:
    """Вернуть односторонний хеш sha256(password + salt)."""
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def load_json(path: Path, default: Any) -> Any:
    """Прочитать JSON-файл; при отсутствии или повреждении вернуть default."""
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    """Записать данные в JSON-файл, создав директорию при необходимости."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
