"""Сервис смен и операций по балансу."""

from __future__ import annotations

from datetime import datetime
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


def open_shift(worker: User, opening_balance: float | int | str | Decimal, session=None) -> Shift:
    """Открывает смену и создаёт стартовую транзакцию.

    :param worker: пользователь
    :param opening_balance: стартовый лимит
    :return: созданный Shift
    :raises ValidationError: если сумма некорректна или смена уже открыта
    """
    balance = _as_decimal(opening_balance)
    if balance <= 0:
        raise ValidationError("Стартовая сумма должна быть больше 0.")

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
            opening_balance=balance,
            current_balance=balance,
            status=ShiftStatus.OPEN,
        )
        local.add(shift)
        local.flush()

        tx = CashTransaction(
            worker_id=worker.id,
            shift_id=shift.id,
            type=CashTransactionType.OPENING,
            amount_delta=balance,
        )
        local.add(tx)
        local.flush()
        return shift


def close_open_shifts() -> int:
    """Закрывает все активные смены (используется в автозакрытии).

    :return: количество закрытых смен
    """
    now = datetime.utcnow()
    with db_session() as session:
        opened = (
            session.query(Shift)
            .filter(Shift.status == ShiftStatus.OPEN)
            .all()
        )
        for shift in opened:
            shift.status = ShiftStatus.CLOSED
            shift.closed_at = now
        return len(opened)


def adjust_balance(
    worker: User,
    delta: float | int | str | Decimal,
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
    with db_session(session=session) as local:
        current_shift = local.get(Shift, shift.id)
        current_shift.current_balance = (current_shift.current_balance or 0) + amount
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
