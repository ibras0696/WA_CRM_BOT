"""Утилиты для работы с часовыми поясами и БД."""

from __future__ import annotations

from datetime import datetime


def adapt_datetime_for_db(value: datetime, bind) -> datetime:
    """Преобразует datetime к форме, понятной текущему диалекту БД.

    SQLite не понимает tz-aware значения, поэтому убираем tzinfo.
    Для остальных диалектов возвращаем как есть.
    """
    if value is None:
        return value
    dialect_name = None
    if bind is not None:
        dialect = getattr(bind, "dialect", None)
        if dialect:
            dialect_name = getattr(dialect, "name", None)
    if dialect_name == "sqlite":
        return value.replace(tzinfo=None)
    return value


__all__ = ["adapt_datetime_for_db"]
