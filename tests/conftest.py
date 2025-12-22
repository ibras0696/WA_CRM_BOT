"""Базовые фикстуры для тестов сервисов."""

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Добавляем корень проекта в PYTHONPATH для pytest внутри контейнера
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from crm_bot.core.models import Base, User, UserRole


@pytest.fixture()
def keyboard_spy(monkeypatch):
    """
    Переопределяет отправку клавиатур, чтобы не ходить в сеть и собирать параметры.
    Возвращает список вызовов для проверок.
    """
    calls = []

    def fake_sender(chat_id, *, body, buttons, header=None, footer=None, payload=None):
        calls.append(
            {
                "chat_id": chat_id,
                "body": body,
                "header": header,
                "footer": footer,
                "buttons": list(buttons),
                "payload": payload,
            }
        )
        return {"result": True}

    from crm_bot.handlers import admin as admin_handlers
    from crm_bot.handlers import manage as manage_handlers

    monkeypatch.setattr(admin_handlers, "base_wa_kb_sender", fake_sender)
    monkeypatch.setattr(manage_handlers, "base_wa_kb_sender", fake_sender)
    return calls


@pytest.fixture(scope="function")
def engine():
    """Тестовый SQLite engine (in-memory, общий для всех сессий в тесте)."""
    url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    eng = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy.pool").pool.StaticPool,
    )
    yield eng


@pytest.fixture(scope="function")
def session(engine):
    """Сессия с чистой схемой перед каждым тестом."""
    with engine.begin() as conn:
        Base.metadata.drop_all(bind=conn)
        Base.metadata.create_all(bind=conn)

    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    sess = SessionLocal()

    # Подменяем глобальные ссылки на engine/SessionLocal
    import crm_bot.core.db as db

    db.SessionLocal = SessionLocal
    db.engine = engine

    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


@pytest.fixture()
def admin_user(session):
    """Создаёт активного админа."""
    admin = User(phone="70000000000@c.us", role=UserRole.ADMIN, is_active=True)
    session.add(admin)
    session.flush()
    return admin


@pytest.fixture()
def worker_user(session):
    """Создаёт активного сотрудника."""
    worker = User(phone="71111111111@c.us", role=UserRole.WORKER, is_active=True)
    session.add(worker)
    session.flush()
    return worker
