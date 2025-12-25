"""Общая логика клиентского меню (текстовые команды «Админ» / «Менеджер»)."""

from __future__ import annotations

import logging

from whatsapp_chatbot_python import Notification

from crm_bot.handlers.admin import admin_menu_handler
from crm_bot.handlers.manage import manage_menu_handler
from crm_bot.services import users as user_service
from crm_bot.utils.auth import is_authorized_admin

MENU_HELP_TEXT = "Напишите «Админ» или «Менеджер», чтобы открыть меню."
FULL_HELP_TEXT = (
    "👋 *CRM WA Bot* помогает вести выдачи и лимиты прямо в WhatsApp.\n\n"
    "🔐 Доступ выдаёт администратор. Пока ваш номер не активирован, бот отвечает только подсказкой.\n\n"
    "👑 *Админ меню* — напишите `Админ`:\n"
    "• добавление/отключение сотрудников\n"
    "• корректировка лимита (нал или банк)\n"
    "• удаление операций и отчёты за период\n"
    "• кнопка «Полный отчёт» (день/месяц/год/период)\n\n"
    "👷 *Меню сотрудника* — напишите `Менеджер`:\n"
    "• открыть или закрыть смену (отдельно для налички/банка)\n"
    "• зафиксировать рассрочку (цена, наценка, срок) или обычную фин. операцию\n"
    "• посмотреть текущий лимит по каждому карману и последние операции\n\n"
    "ℹ️ Кнопки приходят в виде клавиатуры. Если нужно начать заново — напишите `Админ` или `Менеджер`, состояние сбросится."
)
ADMIN_FORBIDDEN_TEXT = "Недостаточно прав для открытия админ-меню."
WORKER_FORBIDDEN_TEXT = "Нет доступа. Доступ выдаёт администратор."
HELP_COMMANDS = {"help", "меню", "menu", "помощь"}
ADMIN_MENU_COMMANDS = {"админ", "admin"}
WORKER_MENU_COMMANDS = {"менеджер", "manager", "worker", "сотрудник"}
MENU_COMMANDS = ADMIN_MENU_COMMANDS | WORKER_MENU_COMMANDS
CANCEL_ON_ZERO = True


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
        logging.debug("state cleared for %s", notification.sender)
    except Exception as exc:  # noqa: BLE001
        logging.warning("failed to clear state for %s: %s", notification.sender, exc)


def handle_menu_command(notification: Notification, txt: str | None = None) -> None:
    """Обрабатывает текстовые команды верхнего уровня (Админ/Менеджер)."""
    text = (txt or notification.get_message_text() or "").strip()
    logging.debug("menu command received: sender=%s text=%s", notification.sender, text)
    if not text:
        return

    normalized = text.lower()
    if normalized not in MENU_COMMANDS and normalized not in HELP_COMMANDS:
        return

    state = _get_state(notification)
    if state and normalized in MENU_COMMANDS:
        logging.debug("state cancelled by menu command: sender=%s state=%s", notification.sender, state)
        _clear_state(notification)

    if normalized in ADMIN_MENU_COMMANDS:
        if is_authorized_admin(notification.sender):
            admin_menu_handler(notification)
        else:
            notification.answer(ADMIN_FORBIDDEN_TEXT)
        return

    if normalized in WORKER_MENU_COMMANDS:
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
        notification.answer(FULL_HELP_TEXT)
