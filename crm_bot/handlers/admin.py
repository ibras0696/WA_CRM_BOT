"""Обработчики административной панели."""

from __future__ import annotations

import logging
from datetime import date, datetime

from whatsapp_chatbot_python import Notification

from crm_bot.config import settings
from crm_bot.keyboards.base_kb import base_wa_kb_sender
from crm_bot.services import admin as admin_service
from crm_bot.services import users as user_service
from crm_bot.services import deals as deal_service
from crm_bot.core.models import DealPaymentMethod
from crm_bot.states.admin import (
    AdminAddManagerStates,
    AdminAdjustBalanceStates,
    AdminAnalyticsStates,
    AdminDeleteDealStates,
    AdminDeleteManagerStates,
    AdminFullReportStates,
)
from crm_bot.handlers.utils import handle_menu_shortcut
from crm_bot.utils.fsm import get_state_name, switch_state
from crm_bot.utils.formatting import format_amount

ADMIN_MENU_BUTTONS = [
    "Добавить сотрудника",
    "Отключить сотрудника",
    "Корректировка баланса",
    "Удалить операцию",
    "Отчёт",
    "Отчёт за день",
    "Полный отчёт",
]
FULL_REPORT_BUTTONS = [
    "За день",
    "За месяц",
    "За год",
    "Период",
]
TODAY_DEALS_PREVIEW_LIMIT = 5
CANCEL_KEYWORDS = {"отмена", "cancel", "выход", "stop"}
CANCEL_MESSAGE = "❌ Запрос отменён."
ADMIN_MENU_HINT = "ℹ️ Чтобы вернуться в админ-меню, отправьте `0`."


def _with_admin_hint(text: str) -> str:
    return f"{text}\n\n{ADMIN_MENU_HINT}"


def admin_menu_handler(notification: Notification) -> None:
    """Отправляет основное меню администратора."""
    logging.debug("sending admin menu to %s", notification.sender)
    base_wa_kb_sender(
        notification.sender,
        body="👑 Админ-панель",
        header="Выберите действие",
        buttons=ADMIN_MENU_BUTTONS,
    )


def _send_full_report_menu(notification: Notification) -> None:
    base_wa_kb_sender(
        notification.sender,
        body="📘 Полный отчёт",
        header="Выберите период",
        buttons=FULL_REPORT_BUTTONS,
    )


def admin_buttons_handler(notification: Notification, txt: str) -> None:
    """Реакция на нажатие кнопок админа."""
    logging.debug("admin button handler triggered: sender=%s text=%s", notification.sender, txt)
    match txt:
        case "Добавить сотрудника":
            notification.answer(
                _with_admin_hint("➕ Введите номер сотрудника в формате 7XXXXXXXXXX.")
            )
            notification.state_manager.set_state(
                notification.sender,
                AdminAddManagerStates.SENDER.value,
            )
        case "Отключить сотрудника":
            notification.answer(_with_admin_hint("🚫 Введите номер сотрудника для отключения."))
            notification.state_manager.set_state(
                notification.sender,
                AdminDeleteManagerStates.SENDER.value,
            )
        case "Корректировка баланса":
            notification.answer(_with_admin_hint("⚖️ Введите номер сотрудника для корректировки."))
            notification.state_manager.set_state(
                notification.sender,
                AdminAdjustBalanceStates.WORKER_PHONE.value,
            )
        case "Удалить операцию":
            notification.answer(_prepare_delete_deals_prompt())
            notification.state_manager.set_state(
                notification.sender,
                AdminDeleteDealStates.DEAL_ID.value,
            )
        case "Отчёт":
            notification.answer(
                _with_admin_hint(
                    "📅 Введите даты отчёта: начало и (опционально) конец + номер сотрудника.\n"
                    "Формат: YYYY-MM-DD [YYYY-MM-DD] [номер]\n"
                    "Пример: 2025-01-01 2025-01-31 79991234567"
                )
            )
            notification.state_manager.set_state(
                notification.sender,
                AdminAnalyticsStates.MANAGER_REPORT.value,
            )
        case "Отчёт за день":
            try:
                report = admin_service.build_today_summary()
                notification.answer(report)
            except Exception as exc:  # noqa: BLE001
                notification.answer(str(exc))
        case "Полный отчёт":
            _send_full_report_menu(notification)
        case _ if txt in FULL_REPORT_BUTTONS:
            handle_full_report_choice(notification, txt)
        case _:
            notification.answer("Команда пока не поддерживается.")


def admin_add_new_manager(notification: Notification) -> None:
    """FSM: добавление нового менеджера."""
    text = (notification.get_message_text() or "").strip()
    if handle_menu_shortcut(notification, text, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    if not text:
        notification.answer(_with_admin_hint("Номер не должен быть пустым."))
        return

    try:
        user = admin_service.add_manager(text)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(
        f"✅ Менеджер {user.phone} активирован."
        + (f" Имя: {user.name}." if user.name else "")
    )


def admin_delete_manager(notification: Notification) -> None:
    """FSM: деактивация менеджера."""
    text = (notification.get_message_text() or "").strip()
    if handle_menu_shortcut(notification, text, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    if not text:
        notification.answer(_with_admin_hint("Номер не должен быть пустым."))
        return

    try:
        user = admin_service.disable_manager(text)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(f"⚠️ Доступ для {user.phone} отключён.")


def admin_adjust_balance(notification: Notification) -> None:
    """FSM: ввод суммы корректировки."""
    state = notification.state_manager.get_state(notification.sender)
    state_name = get_state_name(state)
    raw = notification.get_message_text().strip()
    if handle_menu_shortcut(notification, raw, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    if state_name == AdminAdjustBalanceStates.WORKER_PHONE.value:
        notification.state_manager.update_state_data(
            notification.sender,
            {"worker_phone": raw},
        )
        switch_state(notification, AdminAdjustBalanceStates.BALANCE_KIND.value)
        notification.answer(
            _with_admin_hint("Какой баланс корректируем? Напишите `Наличка` или `Банк`.")
        )
        return

    if state_name == AdminAdjustBalanceStates.BALANCE_KIND.value:
        method = _parse_balance_kind(raw)
        if not method:
            notification.answer(_with_admin_hint("Укажите `Наличка` или `Банк`."))
            return
        notification.state_manager.update_state_data(
            notification.sender,
            {"balance_kind": method.value},
        )
        switch_state(notification, AdminAdjustBalanceStates.DELTA.value)
        notification.answer(_with_admin_hint("Введите дельту (+/-) в рублях."))
        return

    data = notification.state_manager.get_state_data(notification.sender) or {}
    worker_phone = data.get("worker_phone")
    balance_kind = data.get("balance_kind") or DealPaymentMethod.CASH.value
    try:
        admin = user_service.ensure_admin(notification.sender)
        admin_service.adjust_worker_balance(admin, worker_phone, raw, balance_kind)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer("✅ Баланс скорректирован.")


def admin_delete_deal(notification: Notification) -> None:
    """FSM: soft-delete операции."""
    raw = notification.get_message_text().strip()
    if handle_menu_shortcut(notification, raw, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    cleaned = raw.lstrip("#").strip()
    try:
        deal_id = int(cleaned)
    except ValueError:
        notification.answer("ID операции должно быть числом.")
        return

    try:
        admin = user_service.ensure_admin(notification.sender)
        admin_service.soft_delete_deal(admin, deal_id)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(f"🗑️ Операция #{deal_id} помечена как удалённая.")


def admin_manager_report(notification: Notification) -> None:
    """FSM: отчёт по периоду и (опционально) сотруднику."""
    text = notification.get_message_text().strip()
    if handle_menu_shortcut(notification, text, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    if not text:
        notification.answer(_with_admin_hint("Укажите даты."))
        return

    normalized = text.lower()
    if normalized in CANCEL_KEYWORDS or text in {"0", "1"}:
        notification.state_manager.delete_state(notification.sender)
        if text in {"0", "1"}:
            from crm_bot.handlers.menu import handle_menu_command

            handle_menu_command(notification, txt=text)
        else:
            notification.answer(CANCEL_MESSAGE)
        return

    parts = text.split()
    try:
        start_date = _parse_date(parts[0])
        end_date = _parse_date(parts[1]) if len(parts) >= 2 else start_date
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return

    worker_phone = parts[2] if len(parts) >= 3 else None
    try:
        report = admin_service.build_deals_report(start_date, end_date, worker_phone)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(report)


def handle_full_report_choice(notification: Notification, choice: str) -> None:
    """Обрабатывает выбор периода для полного отчёта."""
    if choice == "Период":
        notification.state_manager.set_state(
            notification.sender,
            AdminFullReportStates.CUSTOM_RANGE.value,
        )
        notification.answer(
            _with_admin_hint(
                "🗓️ Укажите даты для полного отчёта.\n"
                "Формат: YYYY-MM-DD [YYYY-MM-DD]\n"
                "Пример: 2025-01-01 2025-01-31"
            )
        )
        return

    try:
        start, end = _resolve_quick_full_report_range(choice)
    except ValueError as exc:
        notification.answer(str(exc))
        return

    try:
        report = admin_service.build_full_report(start, end)
        notification.answer(report)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))


def admin_full_report_custom(notification: Notification) -> None:
    """FSM: полный отчёт по произвольному диапазону."""
    text = notification.get_message_text().strip()
    if handle_menu_shortcut(notification, text, allow_worker=False):
        notification.state_manager.delete_state(notification.sender)
        return
    if not text:
        notification.answer(_with_admin_hint("Укажите даты."))
        return

    normalized = text.lower()
    if normalized in CANCEL_KEYWORDS:
        notification.state_manager.delete_state(notification.sender)
        notification.answer(CANCEL_MESSAGE)
        return

    parts = text.split()
    try:
        start_date = _parse_date(parts[0])
        end_date = _parse_date(parts[1]) if len(parts) >= 2 else start_date
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return

    try:
        report = admin_service.build_full_report(start_date, end_date)
        notification.answer(report)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
    finally:
        notification.state_manager.delete_state(notification.sender)


def _parse_date(raw: str) -> date:
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD") from None


def _resolve_quick_full_report_range(choice: str) -> tuple[date, date]:
    today = datetime.now(admin_service.MOSCOW_TZ).date()
    if choice == "За день":
        return today, today
    if choice == "За месяц":
        start = today.replace(day=1)
        return start, today
    if choice == "За год":
        start = date(today.year, 1, 1)
        return start, today
    raise ValueError("Неизвестный период.")


def _prepare_delete_deals_prompt() -> str:
    preview = _format_today_deals()
    return (
        "🗑️ Введите ID операции для удаления (число).\n"
        f"{preview}\n\n{ADMIN_MENU_HINT}"
    )


def _format_today_deals(limit: int = TODAY_DEALS_PREVIEW_LIMIT) -> str:
    deals = deal_service.list_today_deals(limit=limit)
    if not deals:
        return "За сегодня операций ещё нет."

    lines = []
    for item in deals:
        worker_label = item.worker_name or item.worker_phone or "сотрудник не указан"
        amount = format_amount(item.total_amount)
        method = _format_payment_method(item.payment_method)
        comment = f" [{item.comment}]" if item.comment else ""
        type_label = (
            "Рассрочка" if getattr(item, "deal_type", None) == "installment" else "Фин. операция"
        )
        lines.append(
            f"#{item.id} [{type_label}] {item.client_name} — {amount} [{method}] ({worker_label}){comment}"
        )
    return "Операции за сегодня:\n" + "\n".join(lines)


def _format_payment_method(method) -> str:
    if method and str(method) == "bank":
        return "Банк"
    if hasattr(method, "value"):
        if method.value == "bank":
            return "Банк"
    return "Наличка"


def _parse_balance_kind(raw: str) -> DealPaymentMethod | None:
    key = (raw or "").strip().lower()
    if key in {"нал", "наличка", "cash"}:
        return DealPaymentMethod.CASH
    if key in {"банк", "безнал", "bank"}:
        return DealPaymentMethod.BANK
    return None
