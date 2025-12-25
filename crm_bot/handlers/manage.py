import logging
import re
from decimal import Decimal, ROUND_HALF_UP, DecimalException

from whatsapp_chatbot_python import Notification

from crm_bot.keyboards.base_kb import base_wa_kb_sender
from crm_bot.services import deals as deal_service
from crm_bot.services import shifts as shift_service
from crm_bot.services import users as user_service
from crm_bot.services.shifts import get_last_closed_shift
from crm_bot.states.states import States
from crm_bot.utils.fsm import get_state_name, switch_state
from crm_bot.handlers.utils import handle_menu_shortcut, handle_back_command
from crm_bot.core.models import DealPaymentMethod, DealType
from crm_bot.utils.formatting import format_amount

WORKER_MENU_BUTTONS = [
    "Открыть смену",
    "Закрыть смену",
    "Выдача рассрочки",
    "Финансовая операция",
    "Мой баланс",
    "Мои операции",
]

WORKER_MENU_HINT = "ℹ️ Чтобы вернуться в меню сотрудника, напишите `Менеджер`."
DEAL_START_PROMPT = (
    "💰 Введите сумму: `+`  пополнение, `-`  списание. Добавьте комментарий в той же строке.\n"
    "Пример: `+120000 Предоплата` или `-5000 Закуп`."
)
INSTALLMENT_START_PROMPT = "Введите цену товара (руб)."
PAYMENT_METHOD_PROMPT = "💳 Укажите способ: ⁠ *Наличка*⁠ или ⁠ *Банк*⁠."
PAYMENT_METHOD_RETRY = "💳 Напишите одним словом: ⁠ `Наличка`⁠ или ⁠ `Банк`⁠."


def _with_worker_hint(text: str) -> str:
    return f"{text}\n\n{WORKER_MENU_HINT}"

PAYMENT_CHOICES = {
    "наличка": DealPaymentMethod.CASH,
    "нал": DealPaymentMethod.CASH,
    "cash": DealPaymentMethod.CASH,
    "банк": DealPaymentMethod.BANK,
    "безнал": DealPaymentMethod.BANK,
    "bank": DealPaymentMethod.BANK,
}


def _start_deal_flow(notification: Notification) -> None:
    worker = user_service.get_active_user_by_phone(notification.sender)
    if not worker:
        notification.answer("Нет доступа. Доступ выдаёт администратор.")
        return
    if not shift_service.get_active_shift(worker.id):
        notification.answer("Смена не открыта. Откройте смену, чтобы провести операцию.")
        return
    notification.state_manager.set_state(
        notification.sender,
        States.DEAL_AMOUNT.value,
    )
    notification.answer(_with_worker_hint(DEAL_START_PROMPT))


def _start_installment_flow(notification: Notification) -> None:
    worker = user_service.get_active_user_by_phone(notification.sender)
    if not worker:
        notification.answer("Нет доступа. Доступ выдаёт администратор.")
        return
    if not shift_service.get_active_shift(worker.id):
        notification.answer("Смена не открыта. Откройте смену, чтобы оформить рассрочку.")
        return
    notification.state_manager.set_state(
        notification.sender,
        States.INSTALLMENT_PRICE.value,
    )
    notification.answer(_with_worker_hint(INSTALLMENT_START_PROMPT))


def _start_close_shift(notification: Notification, worker) -> None:
    active = shift_service.get_active_shift(worker.id)
    if not active:
        notification.answer("Нет активной смены. Сначала откройте смену.")
        return
    expected_cash = Decimal(active.current_balance_cash or 0)
    expected_bank = Decimal(active.current_balance_bank or 0)
    notification.state_manager.set_state(
        notification.sender,
        States.CLOSE_SHIFT_CASH.value,
    )
    notification.state_manager.update_state_data(
        notification.sender,
        {
            "expected_cash": str(expected_cash),
            "expected_bank": str(expected_bank),
        },
    )
    notification.answer(
        _with_worker_hint(
            "Сверка смены.\n"
            f"В системе по `наличке`: {format_amount(expected_cash)}.\n"
            "Введите фактический остаток наличных."
        )
    )


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
            _start_open_shift(notification, worker)
        case "Закрыть смену":
            _start_close_shift(notification, worker)
        case "Финансовая операция":
            _start_deal_flow(notification)
        case "Выдача рассрочки":
            _start_installment_flow(notification)
        case "Мой баланс":
            _send_balance(notification)
        case "Мои операции":
            _send_deals(notification)
        case _:
            notification.answer("📌 Команда пока не поддерживается.")


def _start_open_shift(notification: Notification, worker) -> None:
    if shift_service.get_active_shift(worker.id):
        notification.answer("Смена уже открыта. Сначала закройте текущую смену.")
        return
    notification.state_manager.set_state(
        notification.sender,
        States.OPEN_SHIFT_CASH.value,
    )
    last_shift = get_last_closed_shift(worker.id)
    suggested_cash = suggested_bank = None
    if last_shift:
        suggested_cash = Decimal(last_shift.current_balance_cash or 0)
        suggested_bank = Decimal(last_shift.current_balance_bank or 0)
        notification.state_manager.update_state_data(
            notification.sender,
            {
                "suggested_cash": str(suggested_cash),
                "suggested_bank": str(suggested_bank),
            },
        )
    cash_hint = f"Вчерашний остаток: {suggested_cash}" if suggested_cash else "Если остатка нет, введите 0."
    notification.answer(
        _with_worker_hint(
            "Укажите стартовый лимит по `наличке`.\n"
            f"{cash_hint}\n"
            "Можно отправить `+`, чтобы принять остаток."
        )
    )


def open_shift_step(notification: Notification) -> None:
    """FSM шаг: ввод суммы для открытия смены."""
    raw = notification.get_message_text().strip()
    if handle_back_command(notification, raw):
        return
    if handle_menu_shortcut(notification, raw):
        notification.state_manager.delete_state(notification.sender)
        return

    state = get_state_name(notification.state_manager.get_state(notification.sender))
    data = notification.state_manager.get_state_data(notification.sender) or {}
    if state == States.OPEN_SHIFT_CASH.value:
        try:
            cash = _resolve_opening_input(raw, data.get("suggested_cash"))
        except ValueError as exc:
            notification.answer(str(exc))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"opening_cash": str(cash)},
        )
        switch_state(notification, States.OPEN_SHIFT_BANK.value)
        bank_hint = (
            f"Вчерашний остаток: {data.get('suggested_bank')}"
            if data.get("suggested_bank")
            else "Если остатка нет, введите 0."
        )
        notification.answer(
            _with_worker_hint(
                "Теперь укажите стартовый лимит по `безналу`.\n"
                f"{bank_hint}\n"
                "Можно отправить `+`, чтобы принять остаток."
            )
        )
        return

    if state == States.OPEN_SHIFT_BANK.value:
        try:
            bank = _resolve_opening_input(raw, data.get("suggested_bank"))
        except ValueError as exc:
            notification.answer(str(exc))
            return
        opening_cash = Decimal(data.get("opening_cash") or "0")
        try:
            user = user_service.get_active_user_by_phone(notification.sender)
            if not user:
                raise Exception("Нет доступа. Обратитесь к админу.")
            shift_service.open_shift(user, opening_cash, bank)
        except Exception as exc:  # noqa: BLE001
            notification.answer(str(exc))
            return
        finally:
            notification.state_manager.delete_state(notification.sender)

        notification.answer("✅ Смена открыта. Можно создавать операции.")


def close_shift_step(notification: Notification) -> None:
    """FSM шаги сверки и закрытия смены."""
    raw = notification.get_message_text().strip()
    if handle_back_command(notification, raw):
        return
    if handle_menu_shortcut(notification, raw):
        notification.state_manager.delete_state(notification.sender)
        return

    state = get_state_name(notification.state_manager.get_state(notification.sender))
    data = notification.state_manager.get_state_data(notification.sender) or {}
    if state == States.CLOSE_SHIFT_CASH.value:
        try:
            amount = _parse_non_negative_decimal(raw)
        except ValueError as exc:
            notification.answer(str(exc))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"reported_cash": str(amount)},
        )
        switch_state(notification, States.CLOSE_SHIFT_BANK.value)
        notification.answer(
            _with_worker_hint(
                f"В системе по `безналу`: {format_amount(Decimal(data.get('expected_bank') or '0'))}.\n"
                "Введите фактический остаток по банку."
            )
        )
        return

    if state == States.CLOSE_SHIFT_BANK.value:
        try:
            reported_bank = _parse_non_negative_decimal(raw)
        except ValueError as exc:
            notification.answer(str(exc))
            return
        reported_cash = Decimal(data.get("reported_cash") or "0")
        expected_cash = Decimal(data.get("expected_cash") or "0")
        expected_bank = Decimal(data.get("expected_bank") or "0")
        try:
            worker = user_service.get_active_user_by_phone(notification.sender)
            if not worker:
                raise Exception("Нет доступа. Обратитесь к админу.")
            closed_shift = shift_service.close_shift(
                worker,
                reported_cash=reported_cash,
                reported_bank=reported_bank,
            )
        except Exception as exc:  # noqa: BLE001
            notification.answer(str(exc))
            return
        finally:
            notification.state_manager.delete_state(notification.sender)

        diff_cash = Decimal(closed_shift.cash_diff or 0)
        diff_bank = Decimal(closed_shift.bank_diff or 0)
        parts = [
            "🔒 Смена закрыта.",
            f"Наличка — система {format_amount(expected_cash)}, факт {format_amount(reported_cash)}, разница {format_amount(diff_cash)}.",
            f"Банк — система {format_amount(expected_bank)}, факт {format_amount(reported_bank)}, разница {format_amount(diff_bank)}.",
        ]
        if diff_cash != 0 or diff_bank != 0:
            parts.append("⚠️ Есть расхождение, администратор увидит его в отчёте.")
        notification.answer("\n".join(parts))
        return

    notification.answer("Неожиданное состояние, начните заново.")


def deal_steps(notification: Notification) -> None:
    """FSM шаги создания операции."""
    state = notification.state_manager.get_state(notification.sender)
    state_name = get_state_name(state)
    text = notification.get_message_text().strip()
    if handle_back_command(notification, text):
        return
    if state_name != States.DEAL_PAYMENT_METHOD.value:
        if handle_menu_shortcut(notification, text):
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
        notification.answer(_with_worker_hint(PAYMENT_METHOD_PROMPT))
        return

    if state_name == States.DEAL_PAYMENT_METHOD.value:
        if handle_menu_shortcut(notification, text):
            notification.state_manager.delete_state(notification.sender)
            return
        method = _parse_payment_method(text)
        if not method:
            notification.answer(_with_worker_hint(PAYMENT_METHOD_RETRY))
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
        message = (
            f"✅ Операция #{deal.id} сохранена.\n"
            f"Сумма: {format_amount(deal.total_amount)}\n"
            f"Способ: {format_payment_method(deal.payment_method)}"
            + (f"\nКомментарий: {deal.comment}" if deal.comment else "")
        )
        if balance_after is not None:
            message += f"\n💼 Баланс: {format_amount(balance_after)}"
        message += "\n\nГотов записать следующую операцию. Если хотите выйти, напишите `Менеджер`."
        notification.answer(message)
        notification.state_manager.delete_state(notification.sender)
        _start_deal_flow(notification)


def installment_steps(notification: Notification) -> None:
    """FSM шаги создания рассрочки."""
    state = notification.state_manager.get_state(notification.sender)
    state_name = get_state_name(state)
    text = notification.get_message_text().strip()
    if handle_back_command(notification, text):
        return
    if handle_menu_shortcut(notification, text):
        notification.state_manager.delete_state(notification.sender)
        return

    data = notification.state_manager.get_state_data(notification.sender) or {}

    if state_name == States.INSTALLMENT_PRICE.value:
        try:
            price = _parse_positive_decimal(text)
        except ValueError as exc:
            notification.answer(str(exc))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"installment_price": str(price)},
        )
        switch_state(notification, States.INSTALLMENT_PERCENT.value)
        notification.answer(_with_worker_hint("Введите процент наценки (например, 20)."))
        return

    if state_name == States.INSTALLMENT_PERCENT.value:
        try:
            percent = _parse_positive_decimal(text)
        except ValueError as exc:
            notification.answer(str(exc))
            return
        if percent < 1 or percent > 100:
            notification.answer(_with_worker_hint("Процент наценки должен быть от 1 до 100."))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"installment_percent": str(percent)},
        )
        switch_state(notification, States.INSTALLMENT_TERM.value)
        notification.answer(_with_worker_hint("Укажите срок в месяцах (например, 6)."))
        return

    if state_name == States.INSTALLMENT_TERM.value:
        try:
            term = _parse_positive_int(text)
        except ValueError as exc:
            notification.answer(str(exc))
            return
        if term < 1 or term > 120:
            notification.answer(_with_worker_hint("Срок может быть от 1 до 120 месяцев (до 10 лет)."))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"installment_term": str(term)},
        )
        try:
            _, _, _, total = _calc_installment_total(data)
        except ValueError as exc:
            notification.answer(str(exc))
            notification.state_manager.delete_state(notification.sender)
            return
        switch_state(notification, States.INSTALLMENT_DOWN_PAYMENT.value)
        notification.answer(
            _with_worker_hint(
                "Введите сумму первоначального взноса (можно 0).\n"
                f"Макс: {format_amount(total)}."
            )
        )
        return

    if state_name == States.INSTALLMENT_DOWN_PAYMENT.value:
        try:
            down_payment = _parse_non_negative_decimal(text)
        except ValueError as exc:
            notification.answer(str(exc))
            return
        try:
            price, percent, markup, total = _calc_installment_total(data)
            term = int(data.get("installment_term"))
        except Exception:  # noqa: BLE001
            notification.answer("Данные рассрочки повреждены, начните заново.")
            notification.state_manager.delete_state(notification.sender)
            return
        if down_payment > total:
            notification.answer(_with_worker_hint(f"Первоначальный взнос не может превышать {format_amount(total)}."))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"installment_down_payment": str(down_payment)},
        )
        switch_state(notification, States.INSTALLMENT_PAYMENT_METHOD.value)
        notification.answer(
            _with_worker_hint("💳 Укажите способ оплаты первого взноса: ⁠ *Наличка*⁠ или ⁠ *Банк*⁠.")
        )
        return

    if state_name == States.INSTALLMENT_PAYMENT_METHOD.value:
        method = _parse_payment_method(text)
        if not method:
            notification.answer(_with_worker_hint(PAYMENT_METHOD_RETRY))
            return
        try:
            user = user_service.get_active_user_by_phone(notification.sender)
            if not user:
                raise Exception("Нет доступа. Обратитесь к админу.")
            price, percent, markup, total = _calc_installment_total(data)
            term = int(data.get("installment_term"))
            down_payment = Decimal(data.get("installment_down_payment") or "0")
            if down_payment > total:
                raise ValueError("Первоначальный взнос превышает сумму рассрочки.")
            remaining = total - down_payment
            monthly = (remaining / term if term else remaining).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            deal = deal_service.create_deal(
                worker=user,
                client_name=None,
                client_phone=None,
                total_amount=-price,
                payment_method=method,
                deal_type=DealType.INSTALLMENT,
                installment_data={
                    "product_price": price,
                    "markup_percent": percent,
                    "markup_amount": markup,
                    "installment_term_months": term,
                    "down_payment_amount": down_payment,
                    "installment_total_amount": total,
                    "monthly_payment_amount": monthly,
                },
            )
        except Exception as exc:  # noqa: BLE001
            notification.answer(str(exc))
            return
        notification.answer(
            "✅ Рассрочка зафиксирована.\n"
            f"ID операции: #{deal.id}\n"
            f"Цена товара: {format_amount(price)}\n"
            f"Наценка: {format_amount(markup)} ({percent}%)\n"
            f"Первый взнос: {format_amount(down_payment)}\n"
            f"Сумма рассрочки: {format_amount(total)}\n"
            f"Ежемесячный платёж: {format_amount(monthly)}\n\n"
            "Готов оформить следующую рассрочку. Если хотите выйти, напишите `Менеджер`."
        )
        notification.state_manager.delete_state(notification.sender)
        _start_installment_flow(notification)
def _send_balance(notification: Notification) -> None:
    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        breakdown = deal_service.get_balance_breakdown(user)
        notification.answer(
            "💼 Баланс смены:\n"
            f"Наличка: {format_amount(breakdown['cash'])}\n"
            f"Банк: {format_amount(breakdown['bank'])}\n"
            f"Итого: {format_amount(breakdown['total'])}"
        )
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


def _send_deals(notification: Notification) -> None:
    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        deals = deal_service.list_worker_deals(user)
        if not deals:
            notification.answer("Операций нет.")
            return
        lines = []
        for d in deals:
            label = format_payment_method(d.payment_method)
            comment = f" ({d.comment})" if d.comment else ""
            type_label = "Рассрочка" if getattr(d, "deal_type", None) == DealType.INSTALLMENT.value else "Операция"
            lines.append(
                f"#{d.id} [{type_label}] {d.client_name or ''} — {format_amount(d.total_amount)} [{label}] ({d.created_at.date()}){comment}"
            )
        notification.answer("🧾 Последние операции:\n" + "\n".join(lines))
        notification.state_manager.set_state(
            notification.sender,
            States.DEAL_DETAILS.value,
        )
        notification.answer("Введите ID операции для подробностей или напишите «Менеджер», чтобы вернуться в меню.")
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


def deal_details_step(notification: Notification) -> None:
    """Позволяет посмотреть подробности операции после списка."""
    text = notification.get_message_text().strip()
    if handle_back_command(notification, text):
        notification.state_manager.delete_state(notification.sender)
        return
    if handle_menu_shortcut(notification, text, allow_admin=False):
        notification.state_manager.delete_state(notification.sender)
        return
    if not text:
        notification.answer("Введите ID операции или напишите «Менеджер» для возврата.")
        return

    normalized = text.lstrip("#").strip()
    if not normalized:
        notification.answer("Введите ID операции или напишите «Менеджер» для возврата.")
        return

    try:
        deal_id = int(normalized)
    except ValueError:
        notification.answer("ID операции должен быть числом.")
        return

    try:
        user = user_service.get_active_user_by_phone(notification.sender)
        if not user:
            raise Exception("Нет доступа. Обратитесь к админу.")
        deal = deal_service.get_worker_deal(user, deal_id)
        if not deal:
            notification.answer("Операция не найдена.")
            return

        extra = ""
        if deal.deal_type == DealType.INSTALLMENT:
            extra = (
                f"Цена: {format_amount(deal.product_price)}\n"
                f"Наценка: {format_amount(deal.markup_amount)} ({deal.markup_percent}%)\n"
                f"Первый взнос: {format_amount(deal.down_payment_amount)}\n"
                f"Сумма рассрочки: {format_amount(deal.installment_total_amount)}\n"
                f"Ежемесячный платёж: {format_amount(deal.monthly_payment_amount)}\n"
            )
        notification.answer(
            "ℹ️ Операция #{id}\n"
            "Тип: {kind}\n"
            "Сумма: {amount}\n"
            "Способ: {method}\n"
            "{extra}"
            "{comment}"
            "Дата: {ts:%d.%m.%Y %H:%M}\n"
            "Введите другой ID или напишите «Менеджер», чтобы вернуться в меню.".format(
                id=deal.id,
                kind="Рассрочка" if deal.deal_type == DealType.INSTALLMENT else "Финансовая операция",
                amount=format_amount(deal.total_amount),
                method=format_payment_method(deal.payment_method),
                extra=extra,
                comment=f"Комментарий: {deal.comment}\n" if deal.comment else "",
                ts=deal.created_at,
            )
        )
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


AMOUNT_PATTERN = re.compile(r"^\s*([+-]\s*\d+(?:[.,]\d+)?)\s*(.*)$")


def _resolve_opening_input(raw: str, suggested: str | None) -> Decimal:
    if raw == "+":
        if suggested is None:
            raise ValueError("Нет сохранённого остатка. Введите сумму вручную.")
        return Decimal(str(suggested))
    try:
        value = Decimal(raw.replace(",", "."))
    except Exception:
        raise ValueError("Сумма должна быть числом.") from None
    if value < 0:
        raise ValueError("Сумма должна быть неотрицательной.")
    return value


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


def _parse_positive_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw.replace(",", "."))
    except Exception:
        raise ValueError("Сумма должна быть числом.") from None
    if value <= 0:
        raise ValueError("Сумма должна быть больше 0.")
    return value


def _parse_positive_int(raw: str) -> int:
    try:
        value = int(raw.strip())
    except Exception:
        raise ValueError("Число должно быть целым.")
    if value <= 0:
        raise ValueError("Число должно быть больше 0.")
    return value


def _parse_non_negative_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw.replace(",", "."))
    except Exception:
        raise ValueError("Сумма должна быть числом.") from None
    if value < 0:
        raise ValueError("Сумма не может быть отрицательной.")
    return value
def _calc_installment_total(data: dict) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    try:
        price = Decimal(str(data["installment_price"]))
        percent = Decimal(str(data["installment_percent"]))
    except (KeyError, TypeError, DecimalException):
        raise ValueError("Данные рассрочки повреждены, начните заново.")
    markup = (price * percent) / Decimal("100")
    total = price + markup
    return price, percent, markup, total
