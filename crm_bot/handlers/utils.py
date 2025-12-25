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
