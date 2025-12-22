import logging

from whatsapp_chatbot_python import GreenAPIBot, Notification
from whatsapp_chatbot_python.filters import TEXT_TYPES

from crm_bot.config import settings
from crm_bot.handlers.admin import (
    ADMIN_MENU_BUTTONS,
    admin_add_new_manager,
    admin_buttons_handler,
    admin_delete_manager,
    admin_delete_deal,
    admin_manager_report,
    admin_menu_handler,
    admin_adjust_balance,
)
from crm_bot.handlers.manage import (
    manage_menu_handler,
    worker_buttons_handler,
    open_shift_step,
    deal_steps,
    WORKER_MENU_BUTTONS,
)
from crm_bot.states.admin import (
    AdminAddManagerStates,
    AdminAdjustBalanceStates,
    AdminAnalyticsStates,
    AdminDeleteDealStates,
    AdminDeleteManagerStates,
)
from crm_bot.states.states import States

AUTHORIZED_ADMIN_SENDERS = set(settings.admin_phones or [])

bot = GreenAPIBot(
    settings.id_instance,
    settings.api_token,
    debug_mode=settings.bot_debug,
    bot_debug_mode=settings.bot_debug,
)

BUTTON_PAYLOAD_KEYS = (
    "interactiveButtonsResponse",
    "buttonsResponseMessage",
    "templateButtonsReplyMessage",
)


def _is_authorized_admin(sender: str) -> bool:
    """Простая проверка на доступ к административным сценариям."""
    return sender in AUTHORIZED_ADMIN_SENDERS


def _handle_menu_command(notification: Notification) -> None:
    """Общая логика обработки текстовых команд."""
    txt = notification.get_message_text()
    match txt:
        case "0":  # Админская панель
            if _is_authorized_admin(notification.sender):
                admin_menu_handler(notification)
        case "1":  # Менеджерская панель
            manage_menu_handler(notification)
        case _:
            # notification.answer(f"Тест: {notification.sender}")
            pass
            # notification.answer("Отправьте 0 (админ) или 1 (меню сотрудника).")


def _get_button_payload(notification: Notification) -> dict:
    message_data = notification.event.get("messageData", {}) or {}
    for key in BUTTON_PAYLOAD_KEYS:
        payload = message_data.get(key)
        if payload:
            return payload
    return {}


def _extract_button_text(payload: dict) -> str:
    candidates: list[str | None] = [
        payload.get("selectedDisplayText"),
        payload.get("displayText"),
        payload.get("title"),
        payload.get("body"),
        payload.get("text"),
    ]
    selected_button_text = payload.get("selectedButtonText")
    if isinstance(selected_button_text, dict):
        candidates.append(selected_button_text.get("displayText"))
        candidates.append(selected_button_text.get("text"))
    button_text = payload.get("buttonText")
    if isinstance(button_text, dict):
        candidates.append(button_text.get("displayText"))
        candidates.append(button_text.get("text"))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _handle_button_payload(notification: Notification) -> None:
    """Общая логика разбора payload от кнопок."""
    payload = _get_button_payload(notification)
    txt = _extract_button_text(payload)
    logging.debug(
        "button payload: sender=%s raw=%s extracted=%s",
        notification.sender,
        payload,
        txt,
    )
    if not txt:
        return

    admin_buttons = set(ADMIN_MENU_BUTTONS)
    worker_buttons = set(WORKER_MENU_BUTTONS)
    if txt in admin_buttons:
        admin_buttons_handler(notification, txt)
    elif txt in worker_buttons:
        worker_buttons_handler(notification, txt)


@bot.router.message(type_message=TEXT_TYPES)
def base_menu_handler(notification: Notification) -> None:
    """Обрабатывает входящие текстовые сообщения (0/1)."""
    logging.debug(
        "incoming text message: sender=%s type=%s text=%s",
        notification.sender,
        notification.event.get("messageData", {}).get("typeMessage"),
        notification.get_message_text(),
    )
    if notification.sender in settings.admin_phones:
        _handle_menu_command(notification)


@bot.router.outgoing_message(type_message=TEXT_TYPES)
def outgoing_base_menu_handler(notification: Notification) -> None:
    """Обрабатывает отправленные вручную текстовые сообщения (0/1) через outgoing hook."""
    logging.debug(
        "outgoing text message: sender=%s type=%s text=%s",
        notification.sender,
        notification.event.get("messageData", {}).get("typeMessage"),
        notification.get_message_text(),
    )
    if notification.sender in settings.admin_phones:
        _handle_menu_command(notification)


@bot.router.message(
    type_message=[
        "buttonsResponseMessage",
        "templateButtonsReplyMessage",
        "interactiveButtonsResponse",
    ]
)
def buttons_handler(notification: Notification) -> None:
    """Обрабатывает нажатия кнопок (admin/worker) по incoming hook."""
    _handle_button_payload(notification)


@bot.router.outgoing_message(
    type_message=[
        "buttonsResponseMessage",
        "templateButtonsReplyMessage",
        "interactiveButtonsResponse",
    ]
)
def outgoing_buttons_handler(notification: Notification) -> None:
    """Обрабатывает нажатия кнопок по outgoing hook (ручные тесты)."""
    _handle_button_payload(notification)


@bot.router.message(
    state=AdminAddManagerStates.SENDER.value,
    type_message=TEXT_TYPES,
)
def add_new_manager(notification: Notification) -> None:
    """FSM: шаг добавления менеджера (ввод номера)."""
    if not _is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_add_new_manager(notification)


@bot.router.message(
    state=AdminDeleteManagerStates.SENDER.value,
    type_message=TEXT_TYPES,
)
def delete_manager(notification: Notification) -> None:
    """FSM: шаг отключения менеджера (ввод номера)."""
    if not _is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_delete_manager(notification)


@bot.router.message(
    state=AdminAnalyticsStates.MANAGER_REPORT.value,
    type_message=TEXT_TYPES,
)
def manager_report(notification: Notification) -> None:
    """FSM: ввод параметров отчёта."""
    if not _is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_manager_report(notification)


@bot.router.message(
    state=[
        AdminAdjustBalanceStates.WORKER_PHONE.value,
        AdminAdjustBalanceStates.DELTA.value,
    ],
    type_message=TEXT_TYPES,
)
def adjust_balance(notification: Notification) -> None:
    """FSM: корректировка баланса (номер → сумма)."""
    if not _is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_adjust_balance(notification)


@bot.router.message(
    state=AdminDeleteDealStates.DEAL_ID.value,
    type_message=TEXT_TYPES,
)
def delete_deal(notification: Notification) -> None:
    """FSM: soft-delete сделки по id."""
    if not _is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_delete_deal(notification)


@bot.router.message(
    state=States.OPEN_SHIFT_AMOUNT,
    type_message=TEXT_TYPES,
)
def open_shift(notification: Notification) -> None:
    """FSM: ввод суммы при открытии смены (worker)."""
    open_shift_step(notification)


@bot.router.message(
    state=[
        States.DEAL_CLIENT_NAME,
        States.DEAL_CLIENT_PHONE,
        States.DEAL_AMOUNT,
    ],
    type_message=TEXT_TYPES,
)
def deal_handler(notification: Notification) -> None:
    """FSM: шаги создания сделки (имя → телефон → сумма)."""
    deal_steps(notification)


if __name__ == "__main__":
    bot.run_forever()
