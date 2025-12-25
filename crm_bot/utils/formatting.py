"""Утилиты форматирования чисел для сообщений бота."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def format_amount(value) -> str:
    """Возвращает число без дробной части с пробелами в качестве разделителей."""
    amount = Decimal(value or 0)
    rounded = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.0f}".replace(",", " ")


__all__ = ["format_amount"]
