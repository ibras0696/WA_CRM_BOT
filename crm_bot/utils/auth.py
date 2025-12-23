"""Утилиты авторизации по номерам телефонов."""

from __future__ import annotations

from crm_bot.config import settings

AUTHORIZED_ADMIN_SENDERS = set(settings.admin_phones or [])


def is_authorized_admin(sender: str) -> bool:
    """Проверяет, имеет ли номер доступ к административному меню."""
    return sender in AUTHORIZED_ADMIN_SENDERS


__all__ = [
    "AUTHORIZED_ADMIN_SENDERS",
    "is_authorized_admin",
]
