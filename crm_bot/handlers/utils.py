"""Вспомогательные функции для обработчиков бота."""

from __future__ import annotations

MENU_SHORTCUTS = {"0", "1"}


def handle_menu_shortcut(notification, text: str | None) -> bool:
    """Если пользователь ввёл 0/1, переводит его в меню и возвращает True."""
    normalized = (text or "").strip()
    if normalized not in MENU_SHORTCUTS:
        return False

    # Ленивый импорт, чтобы избежать циклов.
    from crm_bot.handlers.menu import handle_menu_command

    handle_menu_command(notification, txt=normalized)
    return True


__all__ = ["handle_menu_shortcut", "MENU_SHORTCUTS"]
