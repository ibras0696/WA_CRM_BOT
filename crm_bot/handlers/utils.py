"""Вспомогательные функции для обработчиков бота."""

from __future__ import annotations

CANCEL_KEYWORDS = {"назад", "отмена", "cancel", "stop", "выход"}


def handle_menu_shortcut(
    notification,
    text: str | None,
    *,
    allow_admin: bool = True,
    allow_worker: bool = True,
) -> bool:
    """Если пользователь ввёл команду меню (Админ/Менеджер), переводит его в меню и возвращает True.

    :param allow_admin: реагировать на `Админ`
    :param allow_worker: реагировать на `Менеджер`
    """
    cleaned = (text or "").strip()
    triggered = False

    from crm_bot.handlers.menu import (
        handle_menu_command,
        ADMIN_MENU_COMMANDS,
        WORKER_MENU_COMMANDS,
    )

    lowered = cleaned.lower()

    if allow_admin and lowered in ADMIN_MENU_COMMANDS:
        handle_menu_command(notification, txt="Админ")
        triggered = True

    if allow_worker and lowered in WORKER_MENU_COMMANDS:
        handle_menu_command(notification, txt="Менеджер")
        triggered = True

    return triggered


def handle_back_command(notification, text: str | None, response: str = "Запрос отменён.") -> bool:
    """Отменяет текущий процесс, если пользователь ввёл ключевое слово."""
    cleaned = (text or "").strip().lower()
    if cleaned not in CANCEL_KEYWORDS:
        return False

    manager = getattr(notification, "state_manager", None)
    deleter = getattr(manager, "delete_state", None)
    if callable(deleter):
        try:
            deleter(notification.sender)
        except Exception:  # noqa: BLE001
            pass
    notification.answer(response)
    return True


__all__ = ["handle_menu_shortcut", "handle_back_command"]
