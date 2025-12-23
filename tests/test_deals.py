"""Тесты сервиса сделок."""

from datetime import timedelta
import pytest
from decimal import Decimal

from crm_bot.services import deals, shifts


def test_create_deal_income_increases_balance(session, worker_user):
    shift = shifts.open_shift(worker_user, 200, session=session)
    deal = deals.create_deal(worker_user, "Клиент", "70000000000@c.us", 150, session=session)
    assert deal.id is not None
    assert shift.current_balance == Decimal("350")


def test_create_deal_expense_reduces_balance(session, worker_user):
    shift = shifts.open_shift(worker_user, 300, session=session)
    deal = deals.create_deal(worker_user, "Клиент", None, -80, session=session)
    assert deal.id is not None
    assert shift.current_balance == Decimal("220")


def test_create_deal_insufficient_balance(session, worker_user):
    shifts.open_shift(worker_user, 50, session=session)
    with pytest.raises(deals.ValidationError):
        deals.create_deal(worker_user, "Клиент", None, -100, session=session)


def test_create_deal_no_shift(session, worker_user):
    with pytest.raises(shifts.NoActiveShift):
        deals.create_deal(worker_user, "Клиент", None, 10, session=session)


def test_list_today_deals_filters_old_entries(session, worker_user):
    """В обзоре удаления показываются только сделки за сегодня."""
    shifts.open_shift(worker_user, 500, session=session)
    deal_today = deals.create_deal(worker_user, "Сегодня", None, 100, session=session)
    deal_old = deals.create_deal(worker_user, "Вчера", None, 50, session=session)
    deal_old.created_at = deal_old.created_at - timedelta(days=1)
    session.commit()

    items = deals.list_today_deals(limit=10, session=session)
    ids = [item.id for item in items]

    assert deal_today.id in ids
    assert deal_old.id not in ids
