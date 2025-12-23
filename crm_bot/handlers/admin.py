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
from crm_bot.states.admin import (
    AdminAddManagerStates,
    AdminAdjustBalanceStates,
    AdminAnalyticsStates,
    AdminDeleteDealStates,
    AdminDeleteManagerStates,
)
from crm_bot.utils.fsm import get_state_name, switch_state

ADMIN_MENU_BUTTONS = [
    "Добавить сотрудника",
    "Отключить сотрудника",
    "Корректировка баланса",
    "Удалить сделку",
    "Отчёт",
]
TODAY_DEALS_PREVIEW_LIMIT = 5


def admin_menu_handler(notification: Notification) -> None:
    """Отправляет основное меню администратора."""
    logging.debug("sending admin menu to %s", notification.sender)
    base_wa_kb_sender(
        notification.sender,
        body="Админ Панель",
        header="Меню управления",
        buttons=ADMIN_MENU_BUTTONS,
    )


def admin_buttons_handler(notification: Notification, txt: str) -> None:
    """Реакция на нажатие кнопок админа."""
    logging.debug("admin button handler triggered: sender=%s text=%s", notification.sender, txt)
    match txt:
        case "Добавить сотрудника":
            notification.answer("Введите номер сотрудника в формате 7XXXXXXXXXX.")
            notification.state_manager.set_state(
                notification.sender,
                AdminAddManagerStates.SENDER.value,
            )
        case "Отключить сотрудника":
            notification.answer("Введите номер сотрудника для отключения.")
            notification.state_manager.set_state(
                notification.sender,
                AdminDeleteManagerStates.SENDER.value,
            )
        case "Корректировка баланса":
            notification.answer("Введите номер сотрудника для корректировки.")
            notification.state_manager.set_state(
                notification.sender,
                AdminAdjustBalanceStates.WORKER_PHONE.value,
            )
        case "Удалить сделку":
            notification.answer(_prepare_delete_deals_prompt())
            notification.state_manager.set_state(
                notification.sender,
                AdminDeleteDealStates.DEAL_ID.value,
            )
        case "Отчёт":
            notification.answer(
                "Введите даты отчёта: начало и (опционально) конец + номер сотрудника.\n"
                "Формат: YYYY-MM-DD [YYYY-MM-DD] [номер]\n"
                "Пример: 2025-01-01 2025-01-31 79991234567"
            )
            notification.state_manager.set_state(
                notification.sender,
                AdminAnalyticsStates.MANAGER_REPORT.value,
            )
        case _:
            notification.answer("Команда пока не поддерживается.")


def admin_add_new_manager(notification: Notification) -> None:
    """FSM: добавление нового менеджера."""
    text = (notification.get_message_text() or "").strip()
    if not text:
        notification.answer("Номер не должен быть пустым.")
        return

    try:
        user = admin_service.add_manager(text)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(
        f"Менеджер {user.phone} активирован."
        + (f" Имя: {user.name}." if user.name else "")
    )


def admin_delete_manager(notification: Notification) -> None:
    """FSM: деактивация менеджера."""
    text = (notification.get_message_text() or "").strip()
    if not text:
        notification.answer("Номер не должен быть пустым.")
        return

    try:
        user = admin_service.disable_manager(text)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(f"Доступ для {user.phone} отключён.")


def admin_adjust_balance(notification: Notification) -> None:
    """FSM: ввод суммы корректировки."""
    state = notification.state_manager.get_state(notification.sender)
    state_name = get_state_name(state)
    raw = notification.get_message_text().strip()
    if state_name == AdminAdjustBalanceStates.WORKER_PHONE.value:
        notification.state_manager.update_state_data(
            notification.sender,
            {"worker_phone": raw},
        )
        switch_state(notification, AdminAdjustBalanceStates.DELTA.value)
        notification.answer("Введите дельту (+/-) в рублях.")
        return

    data = notification.state_manager.get_state_data(notification.sender) or {}
    worker_phone = data.get("worker_phone")
    try:
        admin = user_service.get_active_user_by_phone(notification.sender)
        if not admin:
            raise Exception("Админ не найден.")
        admin_service.adjust_worker_balance(admin, worker_phone, raw)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer("Баланс скорректирован.")


def admin_delete_deal(notification: Notification) -> None:
    """FSM: soft-delete сделки."""
    raw = notification.get_message_text().strip()
    try:
        deal_id = int(raw)
    except ValueError:
        notification.answer("ID сделки должно быть числом.")
        return

    try:
        admin = user_service.get_active_user_by_phone(notification.sender)
        if not admin:
            raise Exception("Админ не найден.")
        admin_service.soft_delete_deal(admin, deal_id)
    except Exception as exc:  # noqa: BLE001
        notification.answer(str(exc))
        return
    finally:
        notification.state_manager.delete_state(notification.sender)

    notification.answer(f"Сделка #{deal_id} помечена как удалённая.")


def admin_manager_report(notification: Notification) -> None:
    """FSM: отчёт по периоду и (опционально) сотруднику."""
    text = notification.get_message_text().strip()
    if not text:
        notification.answer("Укажите даты.")
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


def _parse_date(raw: str) -> date:
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD") from None


def _prepare_delete_deals_prompt() -> str:
    preview = _format_today_deals()
    return (
        "Введите ID сделки для удаления (число).\n"
        f"{preview}"
    )


def _format_today_deals(limit: int = TODAY_DEALS_PREVIEW_LIMIT) -> str:
    deals = deal_service.list_today_deals(limit=limit)
    if not deals:
        return "За сегодня сделок ещё нет."

    lines = []
    for item in deals:
        worker_label = item.worker_name or item.worker_phone or "сотрудник не указан"
        amount = f"{item.total_amount:,.2f}".replace(",", " ")
        lines.append(f"#{item.id} {item.client_name} — {amount} ({worker_label})")
    return "Сделки за сегодня:\n" + "\n".join(lines)
