import logging

from whatsapp_chatbot_python import GreenAPIBot, Notification
from whatsapp_chatbot_python.filters import TEXT_TYPES

from crm_bot.config import settings
from crm_bot.handlers.admin import (
    ADMIN_MENU_BUTTONS,
    FULL_REPORT_BUTTONS,
    admin_add_new_manager,
    admin_buttons_handler,
    admin_delete_manager,
    admin_delete_deal,
    admin_manager_report,
    admin_adjust_balance,
    admin_full_report_custom,
    handle_full_report_choice,
)
from crm_bot.handlers.manage import (
    worker_buttons_handler,
    open_shift_step,
    close_shift_step,
    deal_steps,
    installment_steps,
    deal_details_step,
    WORKER_MENU_BUTTONS,
)
from crm_bot.handlers.menu import handle_menu_command
from crm_bot.states.admin import (
    AdminAddManagerStates,
    AdminAdjustBalanceStates,
    AdminAnalyticsStates,
    AdminDeleteDealStates,
    AdminDeleteManagerStates,
    AdminFullReportStates,
)
from crm_bot.states.states import States
from crm_bot.utils.auth import is_authorized_admin

logging.basicConfig(
    level=logging.DEBUG if settings.bot_debug else logging.INFO,
    format="%(asctime)s:crm_bot:%(levelname)s:%(message)s",
)
logger = logging.getLogger(__name__)

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

def _get_button_payload(notification: Notification) -> dict:
    message_data = notification.event.get("messageData", {}) or {}
    for key in BUTTON_PAYLOAD_KEYS:
        payload = message_data.get(key)
        if payload:
            return payload
    return {}


def _extract_button_info(payload: dict) -> tuple[str | None, str]:
    button_id = (
        payload.get("selectedButtonId")
        or payload.get("selectedId")
        or payload.get("buttonId")
        or payload.get("id")
    )
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
    elif isinstance(selected_button_text, str):
        candidates.append(selected_button_text)
    button_text = payload.get("buttonText")
    if isinstance(button_text, dict):
        candidates.append(button_text.get("displayText"))
        candidates.append(button_text.get("text"))
    elif isinstance(button_text, str):
        candidates.append(button_text)
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return button_id, value.strip()
    return button_id, ""


def _handle_button_payload(notification: Notification) -> None:
    """Общая логика разбора payload от кнопок."""
    payload = _get_button_payload(notification)
    button_id, txt = _extract_button_info(payload)
    logger.debug(
        "button payload: sender=%s id=%s text=%s raw=%s",
        notification.sender,
        button_id,
        txt,
        payload,
    )
    if not txt:
        return

    admin_buttons = set(ADMIN_MENU_BUTTONS)
    worker_buttons = set(WORKER_MENU_BUTTONS)
    if txt in admin_buttons:
        logger.debug("admin button matched: %s (%s)", txt, button_id)
        admin_buttons_handler(notification, txt)
    elif txt in FULL_REPORT_BUTTONS:
        logger.debug("admin full report option matched: %s (%s)", txt, button_id)
        handle_full_report_choice(notification, txt)
    elif txt in worker_buttons:
        logger.debug("worker button matched: %s (%s)", txt, button_id)
        worker_buttons_handler(notification, txt)


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
    if not is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_add_new_manager(notification)


@bot.router.message(
    state=AdminDeleteManagerStates.SENDER.value,
    type_message=TEXT_TYPES,
)
def delete_manager(notification: Notification) -> None:
    """FSM: шаг отключения менеджера (ввод номера)."""
    if not is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_delete_manager(notification)


@bot.router.message(
    state=AdminAnalyticsStates.MANAGER_REPORT.value,
    type_message=TEXT_TYPES,
)
def manager_report(notification: Notification) -> None:
    """FSM: ввод параметров отчёта."""
    if not is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_manager_report(notification)


@bot.router.message(
    state=AdminAdjustBalanceStates.WORKER_PHONE.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=AdminAdjustBalanceStates.BALANCE_KIND.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=AdminAdjustBalanceStates.DELTA.value,
    type_message=TEXT_TYPES,
)
def adjust_balance(notification: Notification) -> None:
    """FSM: корректировка баланса (номер → сумма)."""
    if not is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_adjust_balance(notification)


@bot.router.message(
    state=AdminDeleteDealStates.DEAL_ID.value,
    type_message=TEXT_TYPES,
)
def delete_deal(notification: Notification) -> None:
    """FSM: soft-delete операции по id."""
    if not is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_delete_deal(notification)


@bot.router.message(
    state=AdminFullReportStates.CUSTOM_RANGE.value,
    type_message=TEXT_TYPES,
)
def full_report_custom(notification: Notification) -> None:
    """FSM: полный отчёт по произвольному диапазону."""
    if not is_authorized_admin(notification.sender):
        notification.answer("Недостаточно прав для выполнения команды.")
        return
    admin_full_report_custom(notification)


@bot.router.message(
    state=States.OPEN_SHIFT_CASH.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=States.OPEN_SHIFT_BANK.value,
    type_message=TEXT_TYPES,
)
def open_shift(notification: Notification) -> None:
    """FSM: ввод сумм при открытии смены (worker)."""
    open_shift_step(notification)


@bot.router.message(
    state=States.CLOSE_SHIFT_CASH.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=States.CLOSE_SHIFT_BANK.value,
    type_message=TEXT_TYPES,
)
def close_shift(notification: Notification) -> None:
    """FSM: ввод фактических остатков при закрытии смены (worker)."""
    close_shift_step(notification)


@bot.router.message(
    state=States.DEAL_AMOUNT.value,
    type_message=TEXT_TYPES,
)
def deal_handler(notification: Notification) -> None:
    """FSM: ввод суммы операции и комментария."""
    deal_steps(notification)


@bot.router.message(
    state=States.DEAL_PAYMENT_METHOD.value,
    type_message=TEXT_TYPES,
)
def deal_payment_handler(notification: Notification) -> None:
    """FSM: выбор способа оплаты операции."""
    deal_steps(notification)


@bot.router.message(
    state=States.INSTALLMENT_PRICE.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=States.INSTALLMENT_PERCENT.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=States.INSTALLMENT_TERM.value,
    type_message=TEXT_TYPES,
)
@bot.router.message(
    state=States.INSTALLMENT_PAYMENT_METHOD.value,
    type_message=TEXT_TYPES,
)
def installment_handler(notification: Notification) -> None:
    """FSM: сбор данных для рассрочки."""
    installment_steps(notification)


@bot.router.message(
    state=States.DEAL_DETAILS.value,
    type_message=TEXT_TYPES,
)
def deal_details_handler(notification: Notification) -> None:
    """FSM: ввод ID операции из списка."""
    deal_details_step(notification)


@bot.router.message(
    type_message=TEXT_TYPES,
    state=None,
)
def base_menu_handler(notification: Notification) -> None:
    """Обрабатывает входящие текстовые сообщения (Админ/Менеджер)."""
    logger.debug(
        "incoming text message: sender=%s type=%s text=%s",
        notification.sender,
        notification.event.get("messageData", {}).get("typeMessage"),
        notification.get_message_text(),
    )
    handle_menu_command(notification)


@bot.router.outgoing_message(
    type_message=TEXT_TYPES,
    state=None,
)
def outgoing_base_menu_handler(notification: Notification) -> None:
    """Обрабатывает отправленные вручную текстовые сообщения (Админ/Менеджер) через outgoing hook."""
    logger.debug(
        "outgoing text message: sender=%s type=%s text=%s",
        notification.sender,
        notification.event.get("messageData", {}).get("typeMessage"),
        notification.get_message_text(),
    )
    handle_menu_command(notification)


if __name__ == "__main__":
    bot.run_forever()
