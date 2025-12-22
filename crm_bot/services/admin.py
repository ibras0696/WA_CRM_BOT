"""Сервис административных операций."""

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import func

from crm_bot.core.db import db_session
from crm_bot.core.models import Deal, User, UserRole
from crm_bot.services import users as user_service
from crm_bot.services import shifts as shift_service
from crm_bot.services import deals as deal_service


class AdminServiceError(Exception):
    """Базовая ошибка административного сервиса."""


class ValidationError(AdminServiceError):
    """Некорректные данные."""


def add_manager(phone: str, name: str | None = None, session=None) -> User:
    return user_service.add_manager(phone, name, session=session)


def disable_manager(phone: str, session=None) -> User:
    return user_service.disable_manager(phone, session=session)


def adjust_worker_balance(
    admin: User,
    worker_phone: str,
    delta: str | int | float | Decimal,
    session=None,
) -> None:
    """Корректировка баланса сотрудника админом.

    :param admin: инициатор (должен быть админ)
    :param worker_phone: номер сотрудника
    :param delta: изменение баланса
    :raises ValidationError: если не админ или сотрудник не найден
    """
    if admin.role != UserRole.ADMIN:
        raise ValidationError("Только админ может корректировать баланс.")
    worker = user_service.get_active_user_by_phone(worker_phone, session=session)
    if not worker:
        raise ValidationError("Сотрудник не найден или неактивен.")
    shift_service.adjust_balance(worker, delta, created_by=admin, session=session)


def soft_delete_deal(admin: User, deal_id: int, session=None) -> None:
    """Soft-delete сделки от имени админа."""
    deal_service.soft_delete_deal(admin, deal_id, session=session)


def build_deals_report(
    start: date,
    end: date,
    worker_phone: str | None = None,
    session=None,
) -> str:
    """Простой отчёт: количество и сумма сделок за период.

    :param start: дата начала (включительно)
    :param end: дата конца (включительно)
    :param worker_phone: опционально, номер сотрудника
    :return: текст отчёта
    :raises ValidationError: если сотрудник не найден
    """
    with db_session(session=session) as local:
        query = local.query(
            func.count(Deal.id),
            func.coalesce(func.sum(Deal.total_amount), 0),
        ).filter(
            Deal.is_deleted.is_(False),
            Deal.created_at >= datetime.combine(start, datetime.min.time()),
            Deal.created_at <= datetime.combine(end, datetime.max.time()),
        )
        if worker_phone:
            worker = user_service.get_active_user_by_phone(worker_phone, session=local)
            if not worker:
                raise ValidationError("Сотрудник не найден или неактивен.")
            query = query.filter(Deal.worker_id == worker.id)

        count, total = query.one()
        total_amount = Decimal(total or 0).quantize(Decimal("0.01"))
        return (
            f"Отчёт {start} — {end}\n"
            f"Сделок: {count}\n"
            f"Выдано: {total_amount:,.2f}".replace(",", " ")
        )
