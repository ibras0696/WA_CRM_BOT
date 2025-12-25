"""Сервис операций выдачи и возвратов."""

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
    DealType,
    Shift,
    ShiftStatus,
    User,
    UserRole,
)
from crm_bot.services.shifts import NoActiveShift, _as_decimal, MOSCOW_TZ
from crm_bot.utils.timezones import adapt_datetime_for_db


class DealServiceError(Exception):
    """Базовая ошибка сервиса операций."""


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
    deal_type: str | None


def create_deal(
    worker: User,
    client_name: str,
    client_phone: str | None,
    total_amount: float | int | str | Decimal,
    payment_method: DealPaymentMethod | None = None,
    comment: str | None = None,
    *,
    deal_type: DealType = DealType.OPERATION,
    installment_data: dict | None = None,
    session=None,
) -> Deal:
    """Создаёт операцию с изменением текущего баланса смены.

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
        raise ValidationError("Сумма операции должна быть отлична от 0.")
    normalized_client_name = (client_name or "Без имени").strip() or "Без имени"
    normalized_comment = (comment or "").strip() or None
    method = payment_method or DealPaymentMethod.CASH

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

        cash_balance = Decimal(shift.current_balance_cash or 0)
        bank_balance = Decimal(shift.current_balance_bank or 0)
        target_balance = cash_balance if method == DealPaymentMethod.CASH else bank_balance
        if amount < 0 and target_balance + amount < 0:
            raise ValidationError("Недостаточно лимита для списания.")

        deal = Deal(
            worker_id=worker.id,
            shift_id=shift.id,
            client_name=normalized_client_name,
            client_phone=(client_phone or "").strip() or None,
            total_amount=amount,
            payment_method=method,
            comment=normalized_comment,
            deal_type=deal_type,
        )
        if deal_type == DealType.INSTALLMENT and installment_data:
            deal.product_price = installment_data.get("product_price")
            deal.markup_percent = installment_data.get("markup_percent")
            deal.markup_amount = installment_data.get("markup_amount")
            deal.installment_term_months = installment_data.get("installment_term_months")
            deal.down_payment_amount = installment_data.get("down_payment_amount")
            deal.installment_total_amount = installment_data.get("installment_total_amount")
            deal.monthly_payment_amount = installment_data.get("monthly_payment_amount")
        local.add(deal)
        local.flush()

        if method == DealPaymentMethod.CASH:
            shift.current_balance_cash = (shift.current_balance_cash or 0) + amount
        else:
            shift.current_balance_bank = (shift.current_balance_bank or 0) + amount
        shift.current_balance = (shift.current_balance_cash or 0) + (shift.current_balance_bank or 0)
        tx = CashTransaction(
            worker_id=worker.id,
            shift_id=shift.id,
            deal_id=deal.id,
            type=CashTransactionType.DEAL_ISSUED,
            amount_delta=amount,
        )
        local.add(tx)
        local.flush()
        return deal


def soft_delete_deal(admin: User, deal_id: int, session=None) -> Deal:
    """Помечает операцию удалённой (soft-delete).

    :param admin: админ, выполняющий удаление
    :param deal_id: идентификатор операции
    :return: Deal
    :raises Forbidden: если не админ
    :raises ValidationError: если операция не найдена
    """
    if admin.role != UserRole.ADMIN:
        raise Forbidden("Только админ может удалять операции.")

    with db_session(session=session) as local:
        deal = local.get(Deal, deal_id)
        if not deal:
            raise ValidationError("Операция не найдена.")
        deal.is_deleted = True
        local.flush()
        return deal


def list_worker_deals(worker: User, limit: int = 5, session=None) -> Iterable[Deal]:
    """Список последних операций сотрудника.

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
    """Возвращает конкретную операцию сотрудника."""
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
    """Возвращает суммарный баланс активной смены.

    :param worker: пользователь
    :return: Decimal баланс
    :raises NoActiveShift: если нет активной смены
    """
    breakdown = get_balance_breakdown(worker, session=session)
    return breakdown["total"]


def get_balance_breakdown(worker: User, session=None) -> dict[str, Decimal]:
    """Возвращает баланс по наличке и банку."""
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
        cash = Decimal(shift.current_balance_cash or 0)
        bank = Decimal(shift.current_balance_bank or 0)
        return {
            "cash": cash,
            "bank": bank,
            "total": cash + bank,
        }


def list_today_deals(limit: int = 5, session=None) -> List[DealBrief]:
    """Возвращает последние операции за сегодняшний день (для админа)."""
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
                Deal.deal_type,
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
                    deal_type=row.deal_type,
                )
            )
        return brief_list
