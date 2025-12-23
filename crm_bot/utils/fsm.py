"""Утилиты для работы с state_manager разных реализаций."""

from __future__ import annotations

from typing import Any


def _plain_state(value: Any) -> Any:
    """Преобразует enum/state-объекты к строковому значению."""
    if value is None:
        return None
    if hasattr(value, "value"):
        try:
            return value.value
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "name"):
        try:
            return value.name
        except Exception:  # noqa: BLE001
            pass
    return value


def get_state_name(state: Any) -> str | None:
    """Возвращает строковое имя состояния независимо от реализации."""
    if not state:
        return None
    plain = _plain_state(state)
    return plain


def switch_state(notification, state_name: str) -> None:
    """Переключает состояние, сохраняя накопленные данные."""
    manager = getattr(notification, "state_manager", None)
    if not manager:
        return
    plain_state = _plain_state(state_name)

    updater = getattr(manager, "update_state", None)
    if callable(updater):
        updater(notification.sender, plain_state)
        return

    setter = getattr(manager, "set_state", None)
    if not callable(setter):
        return

    data_snapshot = None
    getter = getattr(manager, "get_state_data", None)
    if callable(getter):
        try:
            data_snapshot = getter(notification.sender)
        except Exception:  # noqa: BLE001
            data_snapshot = None

    setter(notification.sender, plain_state)

    if not data_snapshot:
        return

    updater_data = getattr(manager, "update_state_data", None)
    if callable(updater_data):
        try:
            updater_data(notification.sender, data_snapshot)
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "get_state_name",
    "switch_state",
]
