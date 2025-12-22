"""Настройки проекта и загрузка переменных окружения."""

from dataclasses import dataclass
from pathlib import Path
import os
from typing import List

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR.parent / ".env"

load_dotenv(ENV_FILE)





def _as_bool(value: str | None) -> bool:
    """Приводит строковые значения окружения к bool."""
    return str(value).lower() in {"1", "true", "yes", "on"}


def _as_list(value: str | None) -> List[str]:
    """Преобразует строку с запятыми в список номеров."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str
    id_instance: str
    api_token: str
    green_api_host: str
    green_api_media: str
    company_name: str
    admin_phone: str
    admin_phones: list[str]
    bot_debug: bool


settings = Settings(
    database_url=os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@db:5432/crm_bot"
    ),
    id_instance=os.getenv("ID_INSTANCE"),
    api_token=os.getenv("API_TOKEN"),
    green_api_host=os.getenv("GREEN_API_HOST", "https://api.green-api.com"),
    green_api_media=os.getenv("GREEN_API_MEDIA", "https://media.green-api.com"),
    company_name=os.getenv("COMPANY_NAME", "CRM Bot"),
    admin_phone=os.getenv("ADMIN_PHONE"),
    admin_phones=_as_list(os.getenv("ADMIN_PHONES")) or _as_list(os.getenv("ADMIN_PHONE")),
    bot_debug=_as_bool(os.getenv("BOT_DEBUG", "False")),
)

if __name__ == "__main__":
    t = settings.id_instance
    print(type(t), t)
