"""Вспомогательные функции для обработчиков бота."""

from __future__ import annotations


def handle_menu_shortcut(
    notification,
    text: str | None,
    *,
    allow_admin: bool = True,
    allow_worker: bool = True,
) -> bool:
    """Если пользователь ввёл 0/1, переводит его в меню и возвращает True.

    :param allow_admin: реагировать на `0`
    :param allow_worker: реагировать на `1`
    """
    cleaned = (text or "").strip()
    triggered = False

    from crm_bot.handlers.menu import handle_menu_command

    if allow_admin and cleaned == "0":
        handle_menu_command(notification, txt="0")
        triggered = True

    if allow_worker and cleaned == "1":
        handle_menu_command(notification, txt="1")
        triggered = True

    return triggered


__all__ = ["handle_menu_shortcut"]
