"""Интеграционные тесты пользовательских сценариев (кнопки/FSM)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crm_bot.core.models import Deal, Shift, ShiftStatus, User, UserRole
from crm_bot.handlers import admin as admin_handlers
from crm_bot.handlers import manage as manage_handlers
from crm_bot.handlers import menu as menu_handlers
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
    assert state_manager.get_state(worker_user.phone) == States.OPEN_SHIFT_AMOUNT.value

    notification.set_message_text("150")
    manage_handlers.open_shift_step(notification)
    assert notification.answers[-1] == "✅ Смена открыта. Можно создавать сделки."

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
    assert state_manager.get_state(worker_user.phone) == States.DEAL_AMOUNT.value

    notification.set_message_text("+120 Продажа")
    manage_handlers.deal_steps(notification)
    assert state_manager.get_state(worker_user.phone) == States.DEAL_PAYMENT_METHOD.value

    notification.set_message_text("Наличка")
    manage_handlers.deal_steps(notification)
    assert "Сделка #" in notification.answers[-1]

    session.expire_all()
    deal = session.query(Deal).one()
    assert deal.total_amount == Decimal("120")
    assert deal.payment_method.value == "cash"
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
    notif_deal.set_message_text("+150 Тест")
    manage_handlers.deal_steps(notif_deal)
    notif_deal.set_message_text("Банк")
    manage_handlers.deal_steps(notif_deal)

    notification = FakeNotification(sender=worker_user.phone, state_manager=DummyStateManager())
    manage_handlers.worker_buttons_handler(notification, "Мой баланс")
    assert "Текущий лимит" in notification.answers[-1]

    manage_handlers.worker_buttons_handler(notification, "Мои сделки")
    assert any("Последние сделки" in msg for msg in notification.answers)


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
    assert "Всего сделок: 2" in notification.answers[-1]
    assert "💸 Выдачи" in notification.answers[-1]


def test_menu_handler_routes_to_admin(monkeypatch, admin_user):
    """Текст '0' от админа запускает меню."""
    from crm_bot.utils import auth

    auth.AUTHORIZED_ADMIN_SENDERS.clear()
    auth.AUTHORIZED_ADMIN_SENDERS.add(admin_user.phone)

    calls = {}

    def fake_admin_menu(notification):
        calls["admin"] = notification.sender

    monkeypatch.setattr(menu_handlers, "admin_menu_handler", fake_admin_menu)

    notification = FakeNotification(sender=admin_user.phone)
    notification.set_message_text("0")
    menu_handlers.handle_menu_command(notification)

    assert calls["admin"] == admin_user.phone


def test_menu_handler_blocks_foreign_admin(monkeypatch):
    """Посторонний номер получает отказ на '0'."""
    from crm_bot.utils import auth

    auth.AUTHORIZED_ADMIN_SENDERS.clear()

    notification = FakeNotification(sender="70000000099@c.us")
    notification.set_message_text("0")
    menu_handlers.handle_menu_command(notification)

    assert notification.answers[-1] == menu_handlers.ADMIN_FORBIDDEN_TEXT


def test_menu_handler_routes_to_worker(monkeypatch, worker_user):
    """Текст '1' от активного сотрудника открывает меню сотрудника."""
    calls = {}

    def fake_worker_menu(notification):
        calls["worker"] = notification.sender

    monkeypatch.setattr(menu_handlers, "manage_menu_handler", fake_worker_menu)

    notification = FakeNotification(sender=worker_user.phone)
    notification.set_message_text("1")
    menu_handlers.handle_menu_command(notification)

    assert calls["worker"] == worker_user.phone


def test_menu_handler_blocks_unknown_worker(monkeypatch):
    """Неавторизованный номер получает подсказку при запросе меню сотрудника."""
    notification = FakeNotification(sender="79999999999@c.us")
    notification.set_message_text("1")
    menu_handlers.handle_menu_command(notification)

    assert notification.answers[-1] == menu_handlers.WORKER_FORBIDDEN_TEXT


def test_menu_handler_returns_help_on_explicit_request(monkeypatch, worker_user):
    """Команда help возвращает подсказку."""
    notification = FakeNotification(sender=worker_user.phone)
    notification.set_message_text("help")
    menu_handlers.handle_menu_command(notification)

    assert notification.answers[-1] == menu_handlers.FULL_HELP_TEXT


def test_menu_handler_ignores_random_text(monkeypatch, worker_user):
    """Посторонние сообщения без состояния игнорируются."""
    notification = FakeNotification(sender=worker_user.phone)
    notification.set_message_text("hello")
    menu_handlers.handle_menu_command(notification)

    assert notification.answers == []


def test_menu_handler_resets_state_when_menu_command(monkeypatch, worker_user):
    """Команда '1' в состоянии FSM сбрасывает процесс и открывает меню."""
    calls = {}

    def fake_worker_menu(notification):
        calls["worker"] = notification.sender

    monkeypatch.setattr(menu_handlers, "manage_menu_handler", fake_worker_menu)

    state_manager = DummyStateManager()
    notification = FakeNotification(sender=worker_user.phone, state_manager=state_manager)
    state_manager.set_state(worker_user.phone, States.DEAL_AMOUNT.value)
    notification.set_message_text("1")
    menu_handlers.handle_menu_command(notification)

    assert calls["worker"] == worker_user.phone
    assert state_manager.get_state(worker_user.phone) is None


def test_menu_handler_keeps_state_on_random_text(monkeypatch, worker_user):
    """Произвольный текст в FSM игнорируется и состояние сохраняется."""
    state_manager = DummyStateManager()
    notification = FakeNotification(sender=worker_user.phone, state_manager=state_manager)
    state_manager.set_state(worker_user.phone, States.DEAL_AMOUNT.value)
    notification.set_message_text("bla-bla")
    menu_handlers.handle_menu_command(notification)

    assert state_manager.get_state(worker_user.phone) == States.DEAL_AMOUNT.value
    assert notification.answers == []
