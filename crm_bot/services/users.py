"""Сервис работы с пользователями и валидацией телефонов."""

from __future__ import annotations

import re

from crm_bot.core.db import db_session
from crm_bot.core.models import User, UserRole


class UserServiceError(Exception):
    """Базовая ошибка сервиса пользователей."""


class ValidationError(UserServiceError):
    """Ошибки валидации входных данных."""


PHONE_PATTERN = re.compile(r"^7\d{10}@c\.us$")


def normalize_phone(raw_phone: str) -> str:
    """Проверяет формат телефона.

    :param raw_phone: строка вида 7XXXXXXXXXX@c.us
    :return: нормализованный номер
    :raises ValidationError: если формат неверный
    """
    phone = (raw_phone or "").strip()
    if not PHONE_PATTERN.match(phone):
        raise ValidationError("Номер должен быть в формате 7XXXXXXXXXX@c.us")
    return phone


def get_active_user_by_phone(phone: str, session=None) -> User | None:
    """Возвращает активного пользователя по номеру.

    :param phone: номер в формате 7XXXXXXXXXX@c.us
    :param session: внешняя сессия (для тестов)
    :return: User или None, если нет активного
    """
    normalized = normalize_phone(phone)
    with db_session(session=session) as local:
        return (
            local.query(User)
            .filter(User.phone == normalized, User.is_active.is_(True))
            .one_or_none()
        )


def add_manager(phone: str, name: str | None = None, session=None) -> User:
    """Создать или активировать менеджера.

    :param phone: номер сотрудника
    :param name: имя (опционально)
    :param session: внешняя сессия (для тестов)
    :return: созданный/обновлённый User
    """
    normalized = normalize_phone(phone)
    with db_session(session=session) as local:
        user = (
            local.query(User)
            .filter(User.phone == normalized)
            .one_or_none()
        )
        if user:
            user.role = UserRole.WORKER
            user.is_active = True
            if name:
                user.name = name
            local.flush()
            return user

        user = User(
            phone=normalized,
            name=name,
            role=UserRole.WORKER,
            is_active=True,
        )
        local.add(user)
        local.flush()
        return user


def disable_manager(phone: str, session=None) -> User:
    """Логически отключить менеджера.

    :param phone: номер сотрудника
    :param session: внешняя сессия (для тестов)
    :return: обновлённый User
    :raises ValidationError: если не найден
    """
    normalized = normalize_phone(phone)
    with db_session(session=session) as local:
        user = (
            local.query(User)
            .filter(User.phone == normalized, User.role == UserRole.WORKER)
            .one_or_none()
        )
        if not user:
            raise ValidationError("Сотрудник не найден.")
        user.is_active = False
        local.flush()
        return user
