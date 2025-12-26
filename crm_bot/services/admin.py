"""Сервис административных операций."""

from __future__ import annotations

from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import logging
import tempfile

from sqlalchemy import func, case, or_

from crm_bot.core.db import db_session
from crm_bot.core.models import Deal, User, UserRole, DealPaymentMethod, DealType, Shift, ShiftStatus
from crm_bot.services import users as user_service
from crm_bot.services import shifts as shift_service
from crm_bot.services import deals as deal_service
from crm_bot.utils.timezones import adapt_datetime_for_db
from crm_bot.utils.formatting import format_amount

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
    method: DealPaymentMethod | str | None = None,
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
    shift_service.adjust_balance(worker, delta, method=method or DealPaymentMethod.CASH, created_by=admin, session=session)


def soft_delete_deal(admin: User, deal_id: int, session=None) -> None:
    """Soft-delete операции от имени админа."""
    deal_service.soft_delete_deal(admin, deal_id, session=session)


def build_deals_report(
    start: date,
    end: date,
    worker_phone: str | None = None,
    session=None,
) -> str:
    """Простой отчёт: количество и сумма операций за период.

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
        local_start = adapt_datetime_for_db(start_dt, local.bind)
        local_end = adapt_datetime_for_db(end_dt, local.bind)

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
            f"Всего операций: {summary.total_count}",
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
            lines.append("По сотрудникам: нет операций за период.")

        mismatch_rows = (
            local.query(
                Shift.closed_at,
                Shift.reported_cash,
                Shift.reported_bank,
                Shift.cash_diff,
                Shift.bank_diff,
                User.name,
                User.phone,
            )
            .outerjoin(User, User.id == Shift.worker_id)
            .filter(
                Shift.closed_at >= local_start,
                Shift.closed_at <= local_end,
                Shift.reported_at.isnot(None),
                or_(
                    func.coalesce(Shift.cash_diff, 0) != 0,
                    func.coalesce(Shift.bank_diff, 0) != 0,
                ),
            )
            .order_by(Shift.closed_at.desc())
            .all()
        )
        if mismatch_rows:
            lines.append("\n🧾 Сверка смен (расхождения):")
            for row in mismatch_rows:
                worker_label = row.name or row.phone or "Не указан"
                expected_cash = _as_decimal(row.reported_cash) + _as_decimal(row.cash_diff)
                expected_bank = _as_decimal(row.reported_bank) + _as_decimal(row.bank_diff)
                lines.append(
                    f"• {worker_label} ({row.closed_at:%d.%m}): "
                    f"нал ожид. {_format_money(expected_cash)} → факт {_format_money(row.reported_cash)} "
                    f"(разн. {_format_money(row.cash_diff)}); "
                    f"банк {_format_money(expected_bank)} → {_format_money(row.reported_bank)} "
                    f"(разн. {_format_money(row.bank_diff)})"
                )

        return "\n".join(lines)


def _format_money(value: Decimal | int | float) -> str:
    return format_amount(value)


def _as_decimal(value) -> Decimal:
    """Безопасно переводит число к Decimal, обрабатывая None."""
    if value is None:
        return Decimal(0)
    return Decimal(value)


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


def _aggregate_for_type(session, filters: list, deal_type: DealType):
    return (
        session.query(*_aggregate_columns())
        .filter(*(filters + [Deal.deal_type == deal_type.value]))
        .one()
    )


def build_today_summary(session=None) -> str:
    today = datetime.now(MOSCOW_TZ).date()
    return build_deals_report(today, today, session=session)


def build_today_balances(session=None) -> str:
    """Показывает текущие остатки по открытым сменам."""
    today = datetime.now(MOSCOW_TZ).date()
    with db_session(session=session) as local:
        rows = (
            local.query(
                User.name,
                User.phone,
                Shift.current_balance_cash,
                Shift.current_balance_bank,
            )
            .join(User, User.id == Shift.worker_id)
            .filter(Shift.status == ShiftStatus.OPEN)
            .order_by(User.name)
            .all()
        )
        if not rows:
            return f"📆 Баланс на {today:%d.%m.%Y}\nНет открытых смен."

        total_cash = sum(_as_decimal(row.current_balance_cash) for row in rows)
        total_bank = sum(_as_decimal(row.current_balance_bank) for row in rows)
        lines = [
            f"📆 Баланс на {today:%d.%m.%Y}",
            f"Открытых смен: {len(rows)}",
            f"Общий баланс: {_format_money(total_cash + total_bank)}",
            f"Наличка: {_format_money(total_cash)}",
            f"Банк: {_format_money(total_bank)}",
        ]
        lines.append("\n👥 Сотрудники:")
        for row in rows:
            cash = _as_decimal(row.current_balance_cash)
            bank = _as_decimal(row.current_balance_bank)
            worker_label = row.name or row.phone or "Не указан"
            lines.append(
                f"• {worker_label}: нал {_format_money(cash)}, банк {_format_money(bank)}, итог {_format_money(cash + bank)}"
            )
        return "\n".join(lines)


def build_full_report(
    start: date,
    end: date,
    session=None,
) -> str:
    """Расширенный отчёт по всем операциям за период (текст)."""
    data = _collect_full_report_data(start, end, session=session)
    return _render_full_report_text(data)


def build_full_report_bundle(
    start: date,
    end: date,
    session=None,
) -> tuple[str, str | None]:
    """Возвращает текст отчёта и путь к PNG с таблицами."""
    data = _collect_full_report_data(start, end, session=session)
    text = _render_full_report_text(data)
    image_path: str | None = None
    try:
        image_path = _render_full_report_image(data)
    except Exception:  # noqa: BLE001
        logging.exception("failed to render full report table")
    return text, image_path


def _collect_full_report_data(
    start: date,
    end: date,
    session=None,
) -> dict:
    """Собирает агрегаты для дальнейшего форматирования."""
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=MOSCOW_TZ)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=MOSCOW_TZ)
    with db_session(session=session) as local:
        start_utc = adapt_datetime_for_db(start_dt.astimezone(ZoneInfo("UTC")), local.bind)
        end_utc = adapt_datetime_for_db(end_dt.astimezone(ZoneInfo("UTC")), local.bind)
        local_start = adapt_datetime_for_db(start_dt, local.bind)
        local_end = adapt_datetime_for_db(end_dt, local.bind)
        base_filters = [
            Deal.is_deleted.is_(False),
            Deal.created_at >= start_utc,
            Deal.created_at <= end_utc,
        ]

        summary_row = (
            local.query(*_aggregate_columns())
            .filter(*base_filters)
            .one()
        )
        installment_stats = _aggregate_for_type(local, base_filters, DealType.INSTALLMENT)
        operation_stats = _aggregate_for_type(local, base_filters, DealType.OPERATION)

        detail_rows = (
            local.query(
                User.phone,
                User.name,
                *_aggregate_columns(),
                Deal.deal_type,
            )
            .outerjoin(User, User.id == Deal.worker_id)
            .filter(*base_filters)
            .group_by(User.id, User.phone, User.name, Deal.deal_type)
            .order_by(func.coalesce(func.sum(Deal.total_amount), 0).desc())
            .all()
        )

        mismatch_rows = (
            local.query(
                Shift.closed_at,
                Shift.reported_cash,
                Shift.reported_bank,
                Shift.cash_diff,
                Shift.bank_diff,
                User.name,
                User.phone,
            )
            .outerjoin(User, User.id == Shift.worker_id)
            .filter(
                Shift.closed_at >= local_start,
                Shift.closed_at <= local_end,
                Shift.reported_at.isnot(None),
                or_(
                    func.coalesce(Shift.cash_diff, 0) != 0,
                    func.coalesce(Shift.bank_diff, 0) != 0,
                ),
            )
            .order_by(Shift.closed_at.desc())
            .all()
        )

        return {
            "start": start,
            "end": end,
            "summary": _serialize_aggregate(summary_row),
            "installments": _serialize_aggregate(installment_stats),
            "operations": _serialize_aggregate(operation_stats),
            "details": [
                {
                    "label": row.name or row.phone or "Не указан",
                    "deal_type": row.deal_type,
                    "kind_label": "Рассрочки" if row.deal_type == DealType.INSTALLMENT.value else "Фин. операции",
                    "turnover": _as_decimal(row.issued_sum) + _as_decimal(row.return_sum),
                    "issued_sum": _as_decimal(row.issued_sum),
                    "return_sum": _as_decimal(row.return_sum),
                    "cash_sum": _as_decimal(row.cash_sum),
                    "bank_sum": _as_decimal(row.bank_sum),
                    "total_count": row.total_count,
                }
                for row in detail_rows
            ],
            "mismatches": [
                {
                    "label": row.name or row.phone or "Не указан",
                    "closed_at": row.closed_at,
                    "cash_expected": _as_decimal(row.reported_cash) + _as_decimal(row.cash_diff),
                    "cash_actual": _as_decimal(row.reported_cash),
                    "cash_diff": _as_decimal(row.cash_diff),
                    "bank_expected": _as_decimal(row.reported_bank) + _as_decimal(row.bank_diff),
                    "bank_actual": _as_decimal(row.reported_bank),
                    "bank_diff": _as_decimal(row.bank_diff),
                }
                for row in mismatch_rows
            ],
        }


def _serialize_aggregate(row) -> dict:
    return {
        "total_count": row.total_count,
        "net_sum": _as_decimal(row.net_sum),
        "issued_sum": _as_decimal(row.issued_sum),
        "issued_count": row.issued_count,
        "return_sum": _as_decimal(row.return_sum),
        "return_count": row.return_count,
        "cash_sum": _as_decimal(row.cash_sum),
        "cash_count": row.cash_count,
        "bank_sum": _as_decimal(row.bank_sum),
        "bank_count": row.bank_count,
    }


def _render_full_report_text(data: dict) -> str:
    summary = data["summary"]
    installments = data["installments"]
    operations = data["operations"]
    turnover = summary["issued_sum"] + summary["return_sum"]
    start = data["start"]
    end = data["end"]
    lines = [
        f"📘 Полный отчёт {start:%d.%m.%Y} — {end:%d.%m.%Y}",
        f"Оборот: {_format_money(turnover)}",
        f"💰 Приходы: +{_format_money(summary['issued_sum'])} (операций {summary['issued_count']})",
        f"💸 Расходы: -{_format_money(summary['return_sum'])} (операций {summary['return_count']})",
        f"🧮 Чистый итог: {_format_money(summary['net_sum'])}",
        f"Наличка: {_format_money(summary['cash_sum'])} (операций {summary['cash_count']})",
        f"Банк: {_format_money(summary['bank_sum'])} (операций {summary['bank_count']})",
        f"Всего операций: {summary['total_count']}",
    ]

    def render_block(stats: dict) -> list[str]:
        return [
            f"  Приходы: +{_format_money(stats['issued_sum'])} (операций {stats['issued_count']})",
            f"  Расходы: -{_format_money(stats['return_sum'])} (операций {stats['return_count']})",
            f"  Чистый итог: {_format_money(stats['net_sum'])}",
            f"  Наличка: {_format_money(stats['cash_sum'])} / Банк: {_format_money(stats['bank_sum'])}",
        ]

    lines.append("\n📗 Рассрочки")
    lines.extend(render_block(installments))
    lines.append("\n💼 Финансовые операции")
    lines.extend(render_block(operations))

    detail_rows = data["details"]
    if detail_rows:
        lines.append("\n👥 По сотрудникам:")
        for row in detail_rows:
            lines.append(
                f"• {row['label']} ({row['kind_label']}): "
                f"оборот {_format_money(row['turnover'])}, "
                f"приход {_format_money(row['issued_sum'])} / расход {_format_money(row['return_sum'])}, "
                f"нал {_format_money(row['cash_sum'])} / банк {_format_money(row['bank_sum'])} "
                f"(операций {row['total_count']})"
            )
    else:
        lines.append("\nПо сотрудникам нет операций за период.")

    mismatch_rows = data["mismatches"]
    if mismatch_rows:
        lines.append("\n🧾 Сверка смен (расхождения):")
        for row in mismatch_rows:
            date_label = row["closed_at"].strftime("%d.%m") if row["closed_at"] else "—"
            lines.append(
                f"• {row['label']} ({date_label}): "
                f"нал ожид. {_format_money(row['cash_expected'])} → факт {_format_money(row['cash_actual'])} "
                f"(разн. {_format_money(row['cash_diff'])}); "
                f"банк {_format_money(row['bank_expected'])} → {_format_money(row['bank_actual'])} "
                f"(разн. {_format_money(row['bank_diff'])})"
            )
    return "\n".join(lines)


def _render_full_report_image(data: dict) -> str:
    import pandas as pd
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    summary = data["summary"]
    turnover = summary["issued_sum"] + summary["return_sum"]

    summary_table = pd.DataFrame(
        [
            ["Период", f"{data['start']:%d.%m.%Y} — {data['end']:%d.%m.%Y}"],
            ["Оборот", _format_money(turnover)],
            ["Приходы", f"+{_format_money(summary['issued_sum'])}"],
            ["Расходы", f"-{_format_money(summary['return_sum'])}"],
            ["Чистый итог", _format_money(summary["net_sum"])],
            ["Наличка", _format_money(summary["cash_sum"])],
            ["Банк", _format_money(summary["bank_sum"])],
            ["Всего операций", summary["total_count"]],
        ],
        columns=["Метрика", "Значение"],
    )

    type_rows = []
    for label, stats in (("Рассрочки", data["installments"]), ("Фин. операции", data["operations"])):
        type_rows.append(
            [
                label,
                f"+{_format_money(stats['issued_sum'])}",
                f"-{_format_money(stats['return_sum'])}",
                _format_money(stats["net_sum"]),
                _format_money(stats["cash_sum"]),
                _format_money(stats["bank_sum"]),
            ]
        )
    type_table = pd.DataFrame(
        type_rows,
        columns=["Тип", "Приходы", "Расходы", "Чистый итог", "Нал", "Банк"],
    )

    detail = data["details"]
    if detail:
        detail_table = pd.DataFrame(
            [
                [
                    row["label"],
                    row["kind_label"],
                    _format_money(row["turnover"]),
                    _format_money(row["issued_sum"]),
                    _format_money(row["return_sum"]),
                    _format_money(row["cash_sum"]),
                    _format_money(row["bank_sum"]),
                    row["total_count"],
                ]
                for row in detail
            ],
            columns=["Сотрудник", "Тип", "Оборот", "Приход", "Расход", "Нал", "Банк", "Кол-во"],
        )
    else:
        detail_table = pd.DataFrame([["—", "—", "—", "—", "—", "—", "—", "0"]], columns=["Сотрудник", "Тип", "Оборот", "Приход", "Расход", "Нал", "Банк", "Кол-во"])

    mismatches = data["mismatches"]
    if mismatches:
        mismatch_table = pd.DataFrame(
            [
                [
                    row["label"],
                    row["closed_at"].strftime("%d.%m") if row["closed_at"] else "",
                    _format_money(row["cash_expected"]),
                    _format_money(row["cash_actual"]),
                    _format_money(row["cash_diff"]),
                    _format_money(row["bank_expected"]),
                    _format_money(row["bank_actual"]),
                    _format_money(row["bank_diff"]),
                ]
                for row in mismatches
            ],
            columns=[
                "Сотрудник",
                "Дата",
                "Нал ожид.",
                "Нал факт",
                "Δ нал",
                "Банк ожид.",
                "Банк факт",
                "Δ банк",
            ],
        )
    else:
        mismatch_table = pd.DataFrame(
            [["—", "—", "—", "—", "—", "—", "—", "—"]],
            columns=["Сотрудник", "Дата", "Нал ожид.", "Нал факт", "Δ нал", "Банк ожид.", "Банк факт", "Δ банк"],
        )

    tables = [
        ("📌 Общие итоги", summary_table),
        ("🧾 По типам операций", type_table),
        ("👥 По сотрудникам", detail_table),
        ("🛟 Сверка смен", mismatch_table),
    ]

    def _table_height(df):
        return 1.4 + 0.3 * len(df)

    fig_height = sum(_table_height(df) for _, df in tables)
    fig, axes = plt.subplots(len(tables), 1, figsize=(11, fig_height))
    if len(tables) == 1:
        axes = [axes]

    for ax, (title, df) in zip(axes, tables, strict=False):
        ax.axis("off")
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=6)
        table = ax.table(
            cellText=df.values,
            colLabels=df.columns,
            cellLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.25)
        for (row_idx, col_idx), cell in table.get_celld().items():
            cell.set_edgecolor("#dcdcdc")
            if row_idx == 0:
                cell.set_facecolor("#f1f5ff")
                cell.set_fontsize(11)

    fig.tight_layout()
    file_path = Path(tempfile.gettempdir()) / f"crm_full_report_{uuid4().hex}.png"
    fig.savefig(file_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return str(file_path)
