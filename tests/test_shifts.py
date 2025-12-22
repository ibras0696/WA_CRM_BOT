"""Тесты сервиса смен."""

import pytest
from decimal import Decimal

from crm_bot.services import shifts


def test_open_shift_creates_shift_and_tx(session, worker_user):
    shift = shifts.open_shift(worker_user, 100, session=session)
    assert shift.id is not None
    assert shift.current_balance == Decimal("100")


def test_open_shift_prevent_double(session, worker_user):
    shifts.open_shift(worker_user, 50, session=session)
    with pytest.raises(shifts.ValidationError):
        shifts.open_shift(worker_user, 10, session=session)


def test_adjust_balance(session, worker_user):
    shift = shifts.open_shift(worker_user, 100, session=session)
    updated = shifts.adjust_balance(worker_user, -30, session=session)
    assert updated.current_balance == Decimal("70")


def test_adjust_balance_no_shift(session, worker_user):
    with pytest.raises(shifts.NoActiveShift):
        shifts.adjust_balance(worker_user, 10, session=session)
