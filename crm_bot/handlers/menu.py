"""Общая логика клиентского меню (текстовые команды 0/1)."""

from __future__ import annotations

import logging

from whatsapp_chatbot_python import Notification

from crm_bot.handlers.admin import admin_menu_handler
from crm_bot.handlers.manage import manage_menu_handler
from crm_bot.services import users as user_service
from crm_bot.utils.auth import is_authorized_admin

MENU_HELP_TEXT = "Отправьте 0 (админ) или 1 (меню сотрудника)."
ADMIN_FORBIDDEN_TEXT = "Недостаточно прав для открытия админ-меню."
WORKER_FORBIDDEN_TEXT = "Нет доступа. Доступ выдаёт администратор."
HELP_COMMANDS = {"help", "меню", "menu"}
MENU_COMMANDS = {"0", "1"}


def _get_state(notification: Notification) -> str | None:
    manager = getattr(notification, "state_manager", None)
    if not manager:
        return None
    getter = getattr(manager, "get_state", None)
    if not callable(getter):
        return None
    try:
        return getter(notification.sender)
    except Exception:  # noqa: BLE001
        return None


def _clear_state(notification: Notification) -> None:
    manager = getattr(notification, "state_manager", None)
    if not manager:
        return
    deleter = getattr(manager, "delete_state", None)
    if not callable(deleter):
        return
    try:
        deleter(notification.sender)
    except Exception as exc:  # noqa: BLE001
        logging.warning("failed to clear state for %s: %s", notification.sender, exc)


def handle_menu_command(notification: Notification, txt: str | None = None) -> None:
    """Обрабатывает текстовые команды верхнего уровня (0/1)."""
    text = (txt or notification.get_message_text() or "").strip()
    logging.debug("menu command received: sender=%s text=%s", notification.sender, text)
    if not text:
        return

    normalized = text.lower()
    if text not in MENU_COMMANDS and normalized not in HELP_COMMANDS:
        return

    state = _get_state(notification)
    if state and text in MENU_COMMANDS:
        logging.debug("state cancelled by menu command: sender=%s state=%s", notification.sender, state)
        _clear_state(notification)

    if text == "0":
        if is_authorized_admin(notification.sender):
            admin_menu_handler(notification)
        else:
            notification.answer(ADMIN_FORBIDDEN_TEXT)
        return

    if text == "1":
        try:
            worker = user_service.get_active_user_by_phone(notification.sender)
        except Exception as exc:  # noqa: BLE001
            logging.warning(
                "failed to resolve worker access: sender=%s err=%s",
                notification.sender,
                exc,
            )
            notification.answer(WORKER_FORBIDDEN_TEXT)
            return

        if worker:
            manage_menu_handler(notification)
        else:
            notification.answer(WORKER_FORBIDDEN_TEXT)
        return

    if normalized in HELP_COMMANDS:
        notification.answer(MENU_HELP_TEXT)
