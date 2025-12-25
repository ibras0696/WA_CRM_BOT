"""Сервис смен и операций по балансу."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal

from crm_bot.core.db import db_session
from crm_bot.core.models import (
    CashTransaction,
    CashTransactionType,
    Shift,
    ShiftStatus,
    User,
)


class ShiftServiceError(Exception):
    """Базовая ошибка смен."""


class NoActiveShift(ShiftServiceError):
    """У пользователя нет активной смены."""


class ValidationError(ShiftServiceError):
    """Входные данные некорректны."""


def _as_decimal(value: float | int | str | Decimal) -> Decimal:
    """Преобразует входное значение к Decimal.

    :param value: число/строка
    :return: Decimal
    :raises ValidationError: если преобразовать нельзя
    """
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("Сумма должна быть числом.") from exc


def get_active_shift(worker_id: int, session=None) -> Shift | None:
    """Возвращает активную смену сотрудника, если есть.

    :param worker_id: идентификатор пользователя
    :return: Shift или None
    """
    with db_session(session=session) as local:
        return (
            local.query(Shift)
            .filter(
                Shift.worker_id == worker_id,
                Shift.status == ShiftStatus.OPEN,
            )
            .one_or_none()
        )


def open_shift(
    worker: User,
    opening_balance_cash: float | int | str | Decimal,
    opening_balance_bank: float | int | str | Decimal,
    session=None,
) -> Shift:
    """Открывает смену и создаёт стартовую транзакцию.

    :param worker: пользователь
    :param opening_balance_cash: стартовый лимит по наличке
    :param opening_balance_bank: стартовый лимит по безналу
    :return: созданный Shift
    :raises ValidationError: если сумма некорректна или смена уже открыта
    """
    cash = _as_decimal(opening_balance_cash)
    bank = _as_decimal(opening_balance_bank)
    if cash < 0 or bank < 0:
        raise ValidationError("Суммы должны быть неотрицательными.")
    if cash == 0 and bank == 0:
        raise ValidationError("Нужно указать хотя бы одно значение больше 0.")
    total = cash + bank

    with db_session(session=session) as local:
        existing = (
            local.query(Shift)
            .filter(
                Shift.worker_id == worker.id,
                Shift.status == ShiftStatus.OPEN,
            )
            .one_or_none()
        )
        if existing:
            raise ValidationError("У вас уже есть открытая смена.")

        shift = Shift(
            worker_id=worker.id,
            opening_balance_cash=cash,
            opening_balance_bank=bank,
            current_balance_cash=cash,
            current_balance_bank=bank,
            opening_balance=total,
            current_balance=total,
            status=ShiftStatus.OPEN,
        )
        local.add(shift)
        local.flush()

        tx = CashTransaction(
            worker_id=worker.id,
            shift_id=shift.id,
            type=CashTransactionType.OPENING,
            amount_delta=total,
        )
        local.add(tx)
        local.flush()
        return shift


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def close_open_shifts(now: datetime | None = None) -> int:
    """Закрывает все активные смены (используется в автозакрытии).

    :return: количество закрытых смен
    """
    current = now or datetime.now(MOSCOW_TZ)
    with db_session() as session:
        opened = (
            session.query(Shift)
            .filter(Shift.status == ShiftStatus.OPEN)
            .all()
        )
        for shift in opened:
            shift.status = ShiftStatus.CLOSED
            shift.closed_at = current
        return len(opened)


def adjust_balance(
    worker: User,
    delta: float | int | str | Decimal,
    *,
    method: str | None = None,
    created_by: User | None = None,
    session=None,
) -> Shift:
    """Корректирует баланс активной смены.

    :param worker: сотрудник
    :param delta: изменение (+/-)
    :param created_by: админ, выполняющий корректировку
    :return: обновлённая Shift
    :raises NoActiveShift: если нет открытой смены
    """
    shift = get_active_shift(worker.id, session=session)
    if not shift:
        raise NoActiveShift("Нет активной смены.")

    amount = _as_decimal(delta)
    method_value = getattr(method, "value", method)
    with db_session(session=session) as local:
        current_shift = local.get(Shift, shift.id)
        if method_value == "bank":
            current_shift.current_balance_bank = (current_shift.current_balance_bank or 0) + amount
        else:
            current_shift.current_balance_cash = (current_shift.current_balance_cash or 0) + amount
        current_shift.current_balance = (current_shift.current_balance_cash or 0) + (current_shift.current_balance_bank or 0)
        tx = CashTransaction(
            worker_id=worker.id,
            shift_id=current_shift.id,
            type=CashTransactionType.ADJUSTMENT,
            amount_delta=amount,
            created_by=created_by.id if created_by else None,
        )
        local.add(tx)
        local.flush()
        return current_shift


def get_last_closed_shift(worker_id: int, session=None) -> Shift | None:
    """Возвращает последнюю закрытую смену сотрудника."""
    with db_session(session=session) as local:
        return (
            local.query(Shift)
            .filter(
                Shift.worker_id == worker_id,
                Shift.status == ShiftStatus.CLOSED,
                Shift.closed_at.isnot(None),
            )
            .order_by(Shift.closed_at.desc())
            .first()
        )


def close_shift(
    worker: User,
    *,
    reported_cash: float | int | str | Decimal | None = None,
    reported_bank: float | int | str | Decimal | None = None,
    session=None,
) -> Shift:
    """Закрывает активную смену конкретного сотрудника."""
    shift = get_active_shift(worker.id, session=session)
    if not shift:
        raise NoActiveShift("Нет активной смены.")
    current_time = datetime.now(MOSCOW_TZ)
    with db_session(session=session) as local:
        current_shift = local.get(Shift, shift.id)
        current_shift.status = ShiftStatus.CLOSED
        current_shift.closed_at = current_time
        if reported_cash is not None or reported_bank is not None:
            expected_cash = Decimal(current_shift.current_balance_cash or 0)
            expected_bank = Decimal(current_shift.current_balance_bank or 0)
            cash_value = _as_decimal(reported_cash if reported_cash is not None else expected_cash)
            bank_value = _as_decimal(reported_bank if reported_bank is not None else expected_bank)
            current_shift.reported_cash = cash_value
            current_shift.reported_bank = bank_value
            current_shift.cash_diff = expected_cash - cash_value
            current_shift.bank_diff = expected_bank - bank_value
            current_shift.reported_at = current_time
        return current_shift
