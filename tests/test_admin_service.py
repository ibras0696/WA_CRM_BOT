"""Тесты административных сервисов."""

import pytest

from crm_bot.services import admin as admin_service, shifts
from crm_bot.core.models import UserRole, DealPaymentMethod


def test_adjust_balance_as_admin(session, admin_user, worker_user):
    shifts.open_shift(worker_user, 100, 0, session=session)
    admin_service.adjust_worker_balance(admin_user, worker_user.phone, -20, DealPaymentMethod.CASH, session=session)
    updated = shifts.get_active_shift(worker_user.id, session=session)
    assert updated.current_balance < 100


def test_adjust_balance_forbidden(session, worker_user):
    worker_user.role = UserRole.WORKER
    with pytest.raises(admin_service.ValidationError):
        admin_service.adjust_worker_balance(worker_user, worker_user.phone, 10, session=session)


def test_soft_delete_deal(session, admin_user, worker_user):
    shifts.open_shift(worker_user, 100, 0, session=session)
    deal = admin_service.deal_service.create_deal(worker_user, "Кл", None, 50, session=session)  # type: ignore[attr-defined]
    admin_service.soft_delete_deal(admin_user, deal.id, session=session)
    assert deal.is_deleted is True
