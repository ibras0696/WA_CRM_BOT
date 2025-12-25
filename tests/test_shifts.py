"""Тесты сервиса смен."""

import pytest
from decimal import Decimal

from crm_bot.services import shifts


def test_open_shift_creates_shift_and_tx(session, worker_user):
    shift = shifts.open_shift(worker_user, 100, 50, session=session)
    assert shift.id is not None
    assert shift.current_balance_cash == Decimal("100")
    assert shift.current_balance_bank == Decimal("50")
    assert shift.current_balance == Decimal("150")


def test_open_shift_prevent_double(session, worker_user):
    shifts.open_shift(worker_user, 50, 0, session=session)
    with pytest.raises(shifts.ValidationError):
        shifts.open_shift(worker_user, 10, 0, session=session)


def test_adjust_balance(session, worker_user):
    shift = shifts.open_shift(worker_user, 100, 0, session=session)
    updated = shifts.adjust_balance(worker_user, -30, method="cash", session=session)
    assert updated.current_balance_cash == Decimal("70")
    assert updated.current_balance == Decimal("70")


def test_adjust_balance_no_shift(session, worker_user):
    with pytest.raises(shifts.NoActiveShift):
        shifts.adjust_balance(worker_user, 10, session=session)


def test_close_shift_with_report(session, worker_user):
    shifts.open_shift(worker_user, 120, 80, session=session)
    closed = shifts.close_shift(worker_user, reported_cash=100, reported_bank=90, session=session)
    assert closed.status == shifts.ShiftStatus.CLOSED
    assert closed.reported_cash == Decimal("100")
    assert closed.reported_bank == Decimal("90")
    assert closed.cash_diff == Decimal("20")
    assert closed.bank_diff == Decimal("-10")
