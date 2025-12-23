"""Сервис сделок и операций выдачи."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, List

from sqlalchemy import func

from crm_bot.core.db import db_session
from crm_bot.core.models import (
    CashTransaction,
    CashTransactionType,
    Deal,
    DealPaymentMethod,
    Shift,
    ShiftStatus,
    User,
    UserRole,
)
from crm_bot.services.shifts import NoActiveShift, _as_decimal, MOSCOW_TZ
from crm_bot.utils.timezones import adapt_datetime_for_db


class DealServiceError(Exception):
    """Базовая ошибка сервиса сделок."""


class ValidationError(DealServiceError):
    """Некорректные данные."""


class Forbidden(DealServiceError):
    """Запрещено выполнять действие."""


@dataclass(frozen=True)
class DealBrief:
    id: int
    client_name: str
    total_amount: Decimal
    created_at: datetime
    worker_phone: str | None
    worker_name: str | None
    payment_method: DealPaymentMethod | None
    comment: str | None


def create_deal(
    worker: User,
    client_name: str,
    client_phone: str | None,
    total_amount: float | int | str | Decimal,
    payment_method: DealPaymentMethod | None = None,
    comment: str | None = None,
    session=None,
) -> Deal:
    """Создаёт сделку с изменением текущего баланса смены.

    :param worker: сотрудник
    :param client_name: имя клиента
    :param client_phone: телефон клиента (опционально)
    :param total_amount: сумма операции (`+` пополнение, `-` списание)
    :return: Deal
    :raises ValidationError: если данные некорректны или лимит недостаточен
    :raises NoActiveShift: если нет активной смены
    """
    amount = _as_decimal(total_amount)
    if amount == 0:
        raise ValidationError("Сумма сделки должна быть отлична от 0.")
    normalized_client_name = (client_name or "Без имени").strip() or "Без имени"
    normalized_comment = (comment or "").strip() or None

    with db_session(session=session) as local:
        shift: Shift | None = (
            local.query(Shift)
            .filter(
                Shift.worker_id == worker.id,
                Shift.status == ShiftStatus.OPEN,
            )
            .one_or_none()
        )
        if not shift:
            raise NoActiveShift("Сначала открой смену.")

        current_balance = Decimal(shift.current_balance or 0)
        if amount < 0 and current_balance + amount < 0:
            raise ValidationError("Недостаточно лимита для списания.")

        deal = Deal(
            worker_id=worker.id,
            shift_id=shift.id,
            client_name=normalized_client_name,
            client_phone=(client_phone or "").strip() or None,
            total_amount=amount,
            payment_method=payment_method or DealPaymentMethod.CASH,
            comment=normalized_comment,
        )
        local.add(deal)
        local.flush()

        new_balance = current_balance + amount
        shift.current_balance = new_balance
        balance_delta = amount
        tx = CashTransaction(
            worker_id=worker.id,
            shift_id=shift.id,
            deal_id=deal.id,
            type=CashTransactionType.DEAL_ISSUED,
            amount_delta=balance_delta,
        )
        local.add(tx)
        local.flush()
        return deal


def soft_delete_deal(admin: User, deal_id: int, session=None) -> Deal:
    """Помечает сделку удалённой (soft-delete).

    :param admin: админ, выполняющий удаление
    :param deal_id: идентификатор сделки
    :return: Deal
    :raises Forbidden: если не админ
    :raises ValidationError: если сделка не найдена
    """
    if admin.role != UserRole.ADMIN:
        raise Forbidden("Только админ может удалять сделки.")

    with db_session(session=session) as local:
        deal = local.get(Deal, deal_id)
        if not deal:
            raise ValidationError("Сделка не найдена.")
        deal.is_deleted = True
        local.flush()
        return deal


def list_worker_deals(worker: User, limit: int = 5, session=None) -> Iterable[Deal]:
    """Список последних сделок сотрудника.

    :param worker: пользователь
    :param limit: сколько вернуть
    :return: Iterable[Deal]
    """
    with db_session(session=session) as local:
        return (
            local.query(Deal)
            .filter(
                Deal.worker_id == worker.id,
                Deal.is_deleted.is_(False),
            )
            .order_by(Deal.created_at.desc())
            .limit(limit)
            .all()
        )


def get_worker_deal(worker: User, deal_id: int, session=None) -> Deal | None:
    """Возвращает конкретную сделку сотрудника."""
    with db_session(session=session) as local:
        return (
            local.query(Deal)
            .filter(
                Deal.id == deal_id,
                Deal.worker_id == worker.id,
                Deal.is_deleted.is_(False),
            )
            .one_or_none()
        )


def get_active_balance(worker: User, session=None) -> Decimal:
    """Возвращает текущий баланс активной смены.

    :param worker: пользователь
    :return: Decimal баланс
    :raises NoActiveShift: если нет активной смены
    """
    with db_session(session=session) as local:
        shift = (
            local.query(Shift)
            .filter(
                Shift.worker_id == worker.id,
                Shift.status == ShiftStatus.OPEN,
            )
            .one_or_none()
        )
        if not shift:
            raise NoActiveShift("Нет активной смены.")
        return Decimal(shift.current_balance or 0)


def list_today_deals(limit: int = 5, session=None) -> List[DealBrief]:
    """Возвращает последние сделки за сегодняшний день (для админа)."""
    today = datetime.now(MOSCOW_TZ).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    end = datetime.combine(today, datetime.max.time(), tzinfo=MOSCOW_TZ).astimezone(timezone.utc)

    with db_session(session=session) as local:
        normalized_start = adapt_datetime_for_db(start, local.bind)
        normalized_end = adapt_datetime_for_db(end, local.bind)
        rows = (
            local.query(
                Deal.id,
                Deal.client_name,
                Deal.total_amount,
                Deal.created_at,
                User.phone.label("worker_phone"),
                User.name.label("worker_name"),
                Deal.payment_method,
                Deal.comment,
            )
            .outerjoin(User, User.id == Deal.worker_id)
            .filter(
                Deal.is_deleted.is_(False),
                Deal.created_at >= normalized_start,
                Deal.created_at <= normalized_end,
            )
            .order_by(Deal.created_at.desc())
            .limit(limit)
            .all()
        )

        brief_list: List[DealBrief] = []
        for row in rows:
            amount = row.total_amount if row.total_amount is not None else Decimal("0")
            brief_list.append(
                DealBrief(
                    id=row.id,
                    client_name=row.client_name,
                    total_amount=amount,
                    created_at=row.created_at,
                    worker_phone=row.worker_phone,
                    worker_name=row.worker_name,
                    payment_method=row.payment_method,
                    comment=row.comment,
                )
            )
        return brief_list
