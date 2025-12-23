import logging
import re
from decimal import Decimal

from whatsapp_chatbot_python import Notification

from crm_bot.keyboards.base_kb import base_wa_kb_sender
from crm_bot.services import deals as deal_service
from crm_bot.services import shifts as shift_service
from crm_bot.services import users as user_service
from crm_bot.services.shifts import get_last_closed_shift
from crm_bot.states.states import States
from crm_bot.utils.fsm import get_state_name, switch_state
from crm_bot.handlers.utils import handle_menu_shortcut
from crm_bot.core.models import DealPaymentMethod

WORKER_MENU_BUTTONS = [
    "Открыть смену",
    "Новая сделка",
    "Мой баланс",
    "Мои сделки",
]

PAYMENT_CHOICES = {
    "наличка": DealPaymentMethod.CASH,
    "нал": DealPaymentMethod.CASH,
    "cash": DealPaymentMethod.CASH,
    "банк": DealPaymentMethod.BANK,
    "безнал": DealPaymentMethod.BANK,
    "bank": DealPaymentMethod.BANK,
}


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
                notification.sender,
                States.OPEN_SHIFT_AMOUNT.value,
            )
            last_shift = get_last_closed_shift(worker.id)
            suggested = None
            if last_shift and last_shift.current_balance:
                suggested = Decimal(last_shift.current_balance or 0)
                notification.state_manager.update_state_data(
                    notification.sender,
                    {"suggested_balance": str(suggested)},
                )
                notification.answer(
                    f"Укажите стартовую сумму смены.\n"
                    f"Вчерашний остаток: {suggested}\n"
                    "Отправьте `+`, чтобы принять остаток, или введите новое значение."
                )
            else:
                notification.answer("Укажите стартовую сумму смены.")
        case "Новая сделка":
            notification.state_manager.set_state(
                notification.sender,
                States.DEAL_AMOUNT.value,
            )
            notification.answer(
                "💰 Введите сумму: `+` — пополнение, `-` — списание. Добавьте комментарий в той же строке.\n"
                "Пример: `+120000 Предоплата` или `-5000 Закуп`."
            )
        case "Мой баланс":
            _send_balance(notification)
        case "Мои сделки":
            _send_deals(notification)
        case _:
            notification.answer("📌 Команда пока не поддерживается.")


def open_shift_step(notification: Notification) -> None:
    """FSM шаг: ввод суммы для открытия смены."""
    amount = notification.get_message_text().strip()
    if handle_menu_shortcut(notification, amount, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        data = notification.state_manager.get_state_data(notification.sender) or {}
        suggested = data.get("suggested_balance")
        if amount == "+":
            if not suggested:
                raise Exception("Нет сохранённого остатка. Введите сумму вручную.")
            shift_service.open_shift(user, suggested)
        else:
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
    if state_name != States.DEAL_PAYMENT_METHOD.value:
        if handle_menu_shortcut(notification, text, allow_worker=False):
            notification.state_manager.delete_state(notification.sender)
            return

    if state_name == States.DEAL_AMOUNT.value:
        try:
            amount, comment = _split_amount_comment(text)
        except ValueError:
            notification.answer("Введите сумму, например `+5000` или `-2000 Возврат`.")
            return

        notification.state_manager.update_state_data(
            notification.sender,
            {"amount": amount, "comment": comment},
        )
        switch_state(notification, States.DEAL_PAYMENT_METHOD.value)
        notification.answer("Укажите способ: Наличка или Банк.")
        return

    if state_name == States.DEAL_PAYMENT_METHOD.value:
        method = _parse_payment_method(text)
        if not method:
            notification.answer("Напишите `Наличка` или `Банк`.")
            return
        data = notification.state_manager.get_state_data(notification.sender) or {}
        amount = data.get("amount")
        comment = data.get("comment")
        if not amount:
            notification.answer("Сумма не найдена, начните заново.")
            notification.state_manager.delete_state(notification.sender)
            return
        balance_after = None
        try:
            user = user_service.get_active_user_by_phone(notification.sender)
            if not user:
                raise Exception("Нет доступа. Обратитесь к админу.")
            deal = deal_service.create_deal(
                worker=user,
                client_name=None,
                client_phone=None,
                total_amount=amount,
                payment_method=method,
                comment=comment,
            )
            try:
                balance_after = deal_service.get_active_balance(user)
            except Exception:  # noqa: BLE001
                balance_after = None
        except Exception as exc:  # noqa: BLE001
            notification.answer(str(exc))
            return
        finally:
            notification.state_manager.delete_state(notification.sender)

        message = (
            f"✅ Сделка #{deal.id} сохранена.\n"
            f"Сумма: {deal.total_amount}\n"
            f"Способ: {format_payment_method(deal.payment_method)}"
            + (f"\nКомментарий: {deal.comment}" if deal.comment else "")
        )
        if balance_after is not None:
            message += f"\n💼 Баланс: {balance_after}"
        notification.answer(message)


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
        lines = []
        for d in deals:
            label = format_payment_method(d.payment_method)
            comment = f" ({d.comment})" if d.comment else ""
            lines.append(
                f"#{d.id} {d.client_name} — {d.total_amount} [{label}] ({d.created_at.date()}){comment}"
            )
        notification.answer("🧾 Последние сделки:\n" + "\n".join(lines))
        notification.state_manager.set_state(
            notification.sender,
            States.DEAL_DETAILS.value,
        )
        notification.answer("Введите ID сделки для подробностей или 0 — чтобы вернуться в меню.")
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


def deal_details_step(notification: Notification) -> None:
    """Позволяет посмотреть подробности сделки после списка."""
    text = notification.get_message_text().strip()
    if not text:
        notification.answer("Введите ID сделки или 0 для выхода.")
        return

    if text == "0":
        handle_menu_shortcut(notification, text, allow_worker=False)
        notification.state_manager.delete_state(notification.sender)
        return

    normalized = text.lstrip("#").strip()
    if not normalized:
        notification.answer("Введите ID сделки или 0 для выхода.")
        return

    try:
        deal_id = int(normalized)
    except ValueError:
        notification.answer("ID сделки должен быть числом.")
        return

    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        deal = deal_service.get_worker_deal(user, deal_id)
        if not deal:
            notification.answer("Сделка не найдена.")
            return

        notification.answer(
            "ℹ️ Сделка #{id}\n"
            "Сумма: {amount}\n"
            "Способ: {method}\n"
            "{comment}"
            "Дата: {ts:%d.%m.%Y %H:%M}\n"
            "Введите другой ID или 0 для выхода.".format(
                id=deal.id,
                amount=deal.total_amount,
                method=format_payment_method(deal.payment_method),
                comment=f"Комментарий: {deal.comment}\n" if deal.comment else "",
                ts=deal.created_at,
            )
        )
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


AMOUNT_PATTERN = re.compile(r"^\s*([+-]?\s*\d+(?:[.,]\d+)?)\s*(.*)$")


def _split_amount_comment(raw: str) -> tuple[str, str | None]:
    match = AMOUNT_PATTERN.match(raw)
    if not match:
        raise ValueError
    amount = match.group(1).replace(" ", "").replace(",", ".")
    comment = match.group(2).strip() or None
    if Decimal(amount) == 0:
        raise ValueError
    return amount, comment


def _parse_payment_method(raw: str) -> DealPaymentMethod | None:
    key = (raw or "").strip().lower()
    return PAYMENT_CHOICES.get(key)


def format_payment_method(method: DealPaymentMethod | None) -> str:
    if method == DealPaymentMethod.BANK:
        return "Банк"
    return "Наличка"
