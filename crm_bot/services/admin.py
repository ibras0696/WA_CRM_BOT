"""Сервис административных операций."""

from __future__ import annotations

from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

from sqlalchemy import func, case

from crm_bot.core.db import db_session
from crm_bot.core.models import Deal, User, UserRole, DealPaymentMethod
from crm_bot.services import users as user_service
from crm_bot.services import shifts as shift_service
from crm_bot.services import deals as deal_service
from crm_bot.utils.timezones import adapt_datetime_for_db

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


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
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=MOSCOW_TZ)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=MOSCOW_TZ)
    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = end_dt.astimezone(timezone.utc)

    with db_session(session=session) as local:
        normalized_start = adapt_datetime_for_db(start_utc, local.bind)
        normalized_end = adapt_datetime_for_db(end_utc, local.bind)

        base_filters = [
            Deal.is_deleted.is_(False),
            Deal.created_at >= normalized_start,
            Deal.created_at <= normalized_end,
        ]

        filters = list(base_filters)
        worker = None
        if worker_phone:
            worker = user_service.get_active_user_by_phone(worker_phone, session=local)
            if not worker:
                raise ValidationError("Сотрудник не найден или неактивен.")
            filters.append(Deal.worker_id == worker.id)

        summary = (
            local.query(*_aggregate_columns())
            .filter(*filters)
            .one()
        )

        lines = [
            f"📊 Отчёт {start:%d.%m.%Y} — {end:%d.%m.%Y}",
            f"Всего сделок: {summary.total_count}",
            f"💸 Выдачи: {_format_money(summary.issued_sum)} (шт. {summary.issued_count})",
            f"↩️ Возвраты: {_format_money(summary.return_sum)} (шт. {summary.return_count})",
            f"🧮 Итог: {_format_money(summary.net_sum)}",
            f"Наличка: {_format_money(summary.cash_sum)} (шт. {summary.cash_count})",
            f"Банк: {_format_money(summary.bank_sum)} (шт. {summary.bank_count})",
        ]

        if worker:
            worker_label = worker.name or worker.phone
            lines.append(f"👤 Сотрудник: {worker_label}")
            return "\n".join(lines)

        detail_rows = (
            local.query(
                User.phone,
                User.name,
                *_aggregate_columns(),
            )
            .outerjoin(User, User.id == Deal.worker_id)
            .filter(*base_filters)
            .group_by(User.id, User.phone, User.name)
            .order_by(func.coalesce(func.sum(Deal.total_amount), 0).desc())
            .all()
        )

        if detail_rows:
            lines.append("\n👥 По сотрудникам:")
            for row in detail_rows:
                worker_label = row.name or row.phone or "Не указан"
                lines.append(
                    f"• {worker_label}: "
                    f"выдачи {_format_money(row.issued_sum)} (шт. {row.issued_count}), "
                    f"возвраты {_format_money(row.return_sum)} (шт. {row.return_count}), "
                    f"итог {_format_money(row.net_sum)} | "
                    f"нал {_format_money(row.cash_sum)} (шт. {row.cash_count}) / "
                    f"банк {_format_money(row.bank_sum)} (шт. {row.bank_count})"
                )
        else:
            lines.append("По сотрудникам: нет сделок за период.")

        return "\n".join(lines)


def _format_money(value: Decimal | int | float) -> str:
    amount = Decimal(value or 0).quantize(Decimal("0.01"))
    return f"{amount:,.2f}".replace(",", " ")


def _aggregate_columns() -> tuple:
    issued_sum = func.coalesce(
        func.sum(case((Deal.total_amount > 0, Deal.total_amount), else_=0)),
        0,
    ).label("issued_sum")
    issued_count = func.coalesce(
        func.sum(case((Deal.total_amount > 0, 1), else_=0)),
        0,
    ).label("issued_count")
    return_sum = func.coalesce(
        func.sum(case((Deal.total_amount < 0, -Deal.total_amount), else_=0)),
        0,
    ).label("return_sum")
    return_count = func.coalesce(
        func.sum(case((Deal.total_amount < 0, 1), else_=0)),
        0,
    ).label("return_count")
    net_sum = func.coalesce(func.sum(Deal.total_amount), 0).label("net_sum")
    total_count = func.count(Deal.id).label("total_count")
    cash_sum = func.coalesce(
        func.sum(
            case(
                (Deal.payment_method == DealPaymentMethod.CASH.value, Deal.total_amount),
                else_=0,
            )
        ),
        0,
    ).label("cash_sum")
    cash_count = func.coalesce(
        func.sum(
            case(
                (Deal.payment_method == DealPaymentMethod.CASH.value, 1),
                else_=0,
            )
        ),
        0,
    ).label("cash_count")
    bank_sum = func.coalesce(
        func.sum(
            case(
                (Deal.payment_method == DealPaymentMethod.BANK.value, Deal.total_amount),
                else_=0,
            )
        ),
        0,
    ).label("bank_sum")
    bank_count = func.coalesce(
        func.sum(
            case(
                (Deal.payment_method == DealPaymentMethod.BANK.value, 1),
                else_=0,
            )
        ),
        0,
    ).label("bank_count")
    return (
        total_count,
        net_sum,
        issued_sum,
        issued_count,
        return_sum,
        return_count,
        cash_sum,
        cash_count,
        bank_sum,
        bank_count,
    )


def build_today_summary(session=None) -> str:
    today = datetime.now(MOSCOW_TZ).date()
    return build_deals_report(today, today, session=session)
