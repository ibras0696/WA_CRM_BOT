"""Тесты сервиса сделок."""

import pytest
from decimal import Decimal

from crm_bot.services import deals, shifts


def test_create_deal_success(session, worker_user):
    shift = shifts.open_shift(worker_user, 200, session=session)
    deal = deals.create_deal(worker_user, "Клиент", "70000000000@c.us", 150, session=session)
    assert deal.id is not None
    assert shift.current_balance == Decimal("50")


def test_create_deal_insufficient_balance(session, worker_user):
    shifts.open_shift(worker_user, 50, session=session)
    with pytest.raises(deals.ValidationError):
        deals.create_deal(worker_user, "Клиент", None, 100, session=session)


def test_create_deal_no_shift(session, worker_user):
    with pytest.raises(shifts.NoActiveShift):
        deals.create_deal(worker_user, "Клиент", None, 10, session=session)
