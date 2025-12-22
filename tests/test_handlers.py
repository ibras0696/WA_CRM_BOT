"""Интеграционные тесты пользовательских сценариев (кнопки/FSM)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crm_bot.core.models import Deal, Shift, ShiftStatus, User, UserRole
from crm_bot.handlers import admin as admin_handlers
from crm_bot.handlers import manage as manage_handlers
from crm_bot.services import shifts as shift_service
from crm_bot.services import deals as deal_service
from crm_bot.states.admin import (
    AdminAddManagerStates,
    AdminAdjustBalanceStates,
    AdminDeleteDealStates,
    AdminAnalyticsStates,
)
from crm_bot.states.states import States


class DummyStateManager:
    """Минимальный state-manager для эмуляции FSM."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._data: dict[str, dict] = {}

    def set_state(self, sender: str, state: str) -> None:
        self._states[sender] = state
        self._data.setdefault(sender, {})

    def get_state(self, sender: str) -> str | None:
        return self._states.get(sender)

    def delete_state(self, sender: str) -> None:
        self._states.pop(sender, None)
        self._data.pop(sender, None)

    def update_state_data(self, sender: str, data: dict) -> None:
        storage = self._data.setdefault(sender, {})
        storage.update(data)

    def get_state_data(self, sender: str) -> dict | None:
        return self._data.get(sender)


class FakeNotification:
    """Подделка для whatsapp_chatbot_python.Notification."""

    def __init__(self, sender: str, text: str = "", state_manager: DummyStateManager | None = None) -> None:
        self.sender = sender
        self._text = text
        self.state_manager = state_manager or DummyStateManager()
        self.answers: list[str] = []
        self.event: dict = {}

    def set_message_text(self, text: str) -> None:
        self._text = text

    def get_message_text(self) -> str:
        return self._text

    def answer(self, text: str) -> None:
        self.answers.append(text)


@pytest.mark.usefixtures("keyboard_spy")
def test_admin_add_manager_flow(session, admin_user):
    """Админ: кнопка → ввод телефона → создание пользователя."""
    state_manager = DummyStateManager()
    notification = FakeNotification(sender=admin_user.phone, state_manager=state_manager)

    admin_handlers.admin_buttons_handler(notification, "Добавить сотрудника")
    assert state_manager.get_state(admin_user.phone) == AdminAddManagerStates.SENDER.value

    notification.set_message_text("72222222222@c.us")
    admin_handlers.admin_add_new_manager(notification)
    assert "Менеджер 72222222222@c.us активирован." in notification.answers[-1]

    session.expire_all()
    created: User | None = (
        session.query(User)
        .filter(User.phone == "72222222222@c.us")
        .one_or_none()
    )
    assert created is not None
    assert created.role == UserRole.WORKER


@pytest.mark.usefixtures("keyboard_spy")
def test_worker_open_shift_pipeline(session, worker_user):
    """Сотрудник: кнопка → ввод суммы → открытая смена в БД."""
    state_manager = DummyStateManager()
    notification = FakeNotification(sender=worker_user.phone, state_manager=state_manager)

    manage_handlers.worker_buttons_handler(notification, "Открыть смену")
    assert state_manager.get_state(worker_user.phone) == States.OPEN_SHIFT_AMOUNT

    notification.set_message_text("150")
    manage_handlers.open_shift_step(notification)
    assert notification.answers[-1] == "Смена открыта."

    session.expire_all()
    shift = (
        session.query(Shift)
        .filter(Shift.worker_id == worker_user.id, Shift.status == ShiftStatus.OPEN)
        .one()
    )
    assert shift.opening_balance == Decimal("150")
    assert shift.current_balance == Decimal("150")


@pytest.mark.usefixtures("keyboard_spy")
def test_worker_deal_pipeline(session, worker_user):
    """Сотрудник: создание сделки через цепочку FSM."""
    shift_service.open_shift(worker_user, 300, session=session)

    state_manager = DummyStateManager()
    notification = FakeNotification(sender=worker_user.phone, state_manager=state_manager)

    manage_handlers.worker_buttons_handler(notification, "Новая сделка")
    assert state_manager.get_state(worker_user.phone) == States.DEAL_CLIENT_NAME

    notification.set_message_text("Иван")
    manage_handlers.deal_steps(notification)
    assert state_manager.get_state(worker_user.phone) == States.DEAL_CLIENT_PHONE

    notification.set_message_text("70000000001@c.us")
    manage_handlers.deal_steps(notification)
    assert state_manager.get_state(worker_user.phone) == States.DEAL_AMOUNT

    notification.set_message_text("120")
    manage_handlers.deal_steps(notification)
    assert "Сделка #" in notification.answers[-1]

    session.expire_all()
    deal = session.query(Deal).one()
    assert deal.client_name == "Иван"
    assert deal.total_amount == Decimal("120")
    assert deal.is_deleted is False


@pytest.mark.usefixtures("keyboard_spy")
def test_worker_balance_and_deals_menu(session, worker_user):
    """Сотрудник: просмотр баланса и последних сделок из меню."""
    # Открываем смену через FSM
    sm_open = DummyStateManager()
    notif_open = FakeNotification(worker_user.phone, state_manager=sm_open)
    manage_handlers.worker_buttons_handler(notif_open, "Открыть смену")
    notif_open.set_message_text("400")
    manage_handlers.open_shift_step(notif_open)

    # Создаём сделку через FSM
    sm_deal = DummyStateManager()
    notif_deal = FakeNotification(worker_user.phone, state_manager=sm_deal)
    manage_handlers.worker_buttons_handler(notif_deal, "Новая сделка")
    notif_deal.set_message_text("Тест Клиент")
    manage_handlers.deal_steps(notif_deal)
    notif_deal.set_message_text("70000000000@c.us")
    manage_handlers.deal_steps(notif_deal)
    notif_deal.set_message_text("150")
    manage_handlers.deal_steps(notif_deal)

    notification = FakeNotification(sender=worker_user.phone, state_manager=DummyStateManager())
    manage_handlers.worker_buttons_handler(notification, "Мой баланс")
    assert "Текущий лимит" in notification.answers[-1]

    manage_handlers.worker_buttons_handler(notification, "Мои сделки")
    assert "Последние сделки" in notification.answers[-1]


@pytest.mark.usefixtures("keyboard_spy")
def test_admin_adjust_balance_flow(session, admin_user, worker_user):
    """Админ: корректировка баланса через два шага FSM."""
    shift_service.open_shift(worker_user, 200, session=session)
    session.commit()

    state_manager = DummyStateManager()
    notification = FakeNotification(admin_user.phone, state_manager=state_manager)

    admin_handlers.admin_buttons_handler(notification, "Корректировка баланса")
    assert state_manager.get_state(admin_user.phone) == AdminAdjustBalanceStates.WORKER_PHONE.value

    notification.set_message_text(worker_user.phone)
    admin_handlers.admin_adjust_balance(notification)
    assert state_manager.get_state(admin_user.phone) == AdminAdjustBalanceStates.DELTA.value

    notification.set_message_text("-50")
    admin_handlers.admin_adjust_balance(notification)
    assert "Баланс скорректирован." in notification.answers[-1]

    session.expire_all()
    shift = shift_service.get_active_shift(worker_user.id, session=session)
    assert shift.current_balance == Decimal("150")


@pytest.mark.usefixtures("keyboard_spy")
def test_admin_delete_deal_flow(session, admin_user, worker_user):
    """Админ: удаление конкретной сделки."""
    shift = shift_service.open_shift(worker_user, 300, session=session)
    deal = deal_service.create_deal(worker_user, "Удалить", None, 120, session=session)
    session.commit()

    state_manager = DummyStateManager()
    notification = FakeNotification(admin_user.phone, state_manager=state_manager)

    admin_handlers.admin_buttons_handler(notification, "Удалить сделку")
    assert state_manager.get_state(admin_user.phone) == AdminDeleteDealStates.DEAL_ID.value

    notification.set_message_text(str(deal.id))
    admin_handlers.admin_delete_deal(notification)
    assert f"Сделка #{deal.id} помечена как удалённая." in notification.answers[-1]

    session.refresh(deal)
    assert deal.is_deleted is True


@pytest.mark.usefixtures("keyboard_spy")
def test_admin_report_flow(session, admin_user, worker_user):
    """Админ: построение отчёта по периоду и сотруднику."""
    shift_service.open_shift(worker_user, 500, session=session)
    deal_service.create_deal(worker_user, "Клиент1", None, 200, session=session)
    deal_service.create_deal(worker_user, "Клиент2", None, 100, session=session)
    session.commit()

    state_manager = DummyStateManager()
    notification = FakeNotification(admin_user.phone, state_manager=state_manager)

    admin_handlers.admin_buttons_handler(notification, "Отчёт")
    assert state_manager.get_state(admin_user.phone) == AdminAnalyticsStates.MANAGER_REPORT.value

    notification.set_message_text(f"2025-01-01 2025-12-31 {worker_user.phone}")
    admin_handlers.admin_manager_report(notification)
    assert "Сделок: 2" in notification.answers[-1]
    assert "Выдано:" in notification.answers[-1]
