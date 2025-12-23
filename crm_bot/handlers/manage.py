import logging

from whatsapp_chatbot_python import Notification

from crm_bot.keyboards.base_kb import base_wa_kb_sender
from crm_bot.services import deals as deal_service
from crm_bot.services import shifts as shift_service
from crm_bot.services import users as user_service
from crm_bot.states.states import States
from crm_bot.utils.fsm import get_state_name, switch_state

WORKER_MENU_BUTTONS = [
    "Открыть смену",
    "Новая сделка",
    "Мой баланс",
    "Мои сделки",
]


def manage_menu_handler(notification: Notification) -> None:
    logging.debug("sending worker menu to %s", notification.sender)
    base_wa_kb_sender(
        notification.sender,
        body="👷 Меню сотрудника",
        header="Выберите действие",
        buttons=WORKER_MENU_BUTTONS,
    )


def worker_buttons_handler(notification: Notification, txt: str) -> None:
    """Реакция на кнопки в меню сотрудника."""
    worker = user_service.get_active_user_by_phone(notification.sender)
    if not worker:
        notification.answer("Нет доступа. Доступ выдаёт администратор.")
        return
    logging.debug("worker button handler triggered: sender=%s text=%s", notification.sender, txt)
    match txt:
        case "Открыть смену":
            notification.state_manager.set_state(
                notification.sender, States.OPEN_SHIFT_AMOUNT
            )
            notification.answer("Укажите стартовую сумму смены.")
        case "Новая сделка":
            notification.state_manager.set_state(
                notification.sender, States.DEAL_CLIENT_NAME
            )
            notification.answer("Имя клиента?")
        case "Мой баланс":
            _send_balance(notification)
        case "Мои сделки":
            _send_deals(notification)
        case _:
            notification.answer("📌 Команда пока не поддерживается.")


def open_shift_step(notification: Notification) -> None:
    """FSM шаг: ввод суммы для открытия смены."""
    amount = notification.get_message_text().strip()
    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        shift_service.open_shift(user, amount)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer("✅ Смена открыта. Можно создавать сделки.")


def deal_steps(notification: Notification) -> None:
    """FSM шаги создания сделки."""
    state = notification.state_manager.get_state(notification.sender)
    state_name = get_state_name(state)
    text = notification.get_message_text().strip()

    if state_name == States.DEAL_CLIENT_NAME:
        notification.state_manager.update_state_data(
            notification.sender, {"client_name": text}
        )
        switch_state(notification, States.DEAL_CLIENT_PHONE)
        notification.answer("📞 Телефон клиента (опционально):")
        return

    data = notification.state_manager.get_state_data(notification.sender) or {}
    if state_name == States.DEAL_CLIENT_PHONE:
        data["client_phone"] = text
        notification.state_manager.update_state_data(notification.sender, data)
        switch_state(notification, States.DEAL_AMOUNT)
        notification.answer("💰 Сумма операции (можно с + или -):")
        return

    if state_name == States.DEAL_AMOUNT:
        client_name = data.get("client_name")
        client_phone = data.get("client_phone")
        amount = text
        try:
            user = user_service.get_active_user_by_phone(notification.sender)
            if not user:
                raise Exception("Нет доступа. Обратитесь к админу.")
            deal = deal_service.create_deal(
                worker=user,
                client_name=client_name,
                client_phone=client_phone,
                total_amount=amount,
            )
        except Exception as exc:  # noqa: BLE001
            notification.answer(str(exc))
            return
        finally:
            notification.state_manager.delete_state(notification.sender)

        notification.answer(
            f"✅ Сделка #{deal.id} сохранена.\n"
            f"Клиент: {deal.client_name}\n"
            f"Сумма: {deal.total_amount}"
        )


def _send_balance(notification: Notification) -> None:
    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        balance = deal_service.get_active_balance(user)
        notification.answer(f"💼 Текущий лимит: {balance}")
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


def _send_deals(notification: Notification) -> None:
    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        deals = deal_service.list_worker_deals(user)
        if not deals:
            notification.answer("Сделок нет.")
            return
        lines = [
            f"#{d.id} {d.client_name} — {d.total_amount} ({d.created_at.date()})"
            for d in deals
        ]
        notification.answer("🧾 Последние сделки:\n" + "\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
