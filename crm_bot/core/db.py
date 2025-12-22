from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from crm_bot.config import settings

# Позволяет подменять engine в тестах
engine = create_engine(
    settings.database_url,
    echo=settings.bot_debug,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_session_override(session_factory: Optional[sessionmaker] = None) -> Session:
    """Возвращает сессию, используя переданную фабрику (для тестов) или глобальную."""
    factory = session_factory or SessionLocal
    return factory()


@contextmanager
def db_session(
    session_factory: Optional[sessionmaker] = None,
    session: Optional[Session] = None,
) -> Iterator[Session]:
    """
    Контекстный менеджер для безопасной работы с БД.

    Если передан session, он используется без авто-commit/rollback (управляет вызывающий код).
    Иначе создаётся новая сессия из session_factory/SessionLocal с авто-commit/rollback.
    """
    if session is not None:
        yield session
        return

    local_session = get_session_override(session_factory)
    try:
        yield local_session
        local_session.commit()
    except Exception:
        local_session.rollback()
        raise
    finally:
        local_session.close()
