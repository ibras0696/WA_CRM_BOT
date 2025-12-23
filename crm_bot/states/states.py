"""Состояния FSM-процессов для бота."""

from whatsapp_chatbot_python.manager.state import BaseStates


class States(BaseStates):
    """Определяет названия шагов пользователя в процессе ввода сделок/платежей."""

    OPEN_SHIFT_AMOUNT = "shift:opening_balance"
    DEAL_AMOUNT = "deal:amount"
    DEAL_PAYMENT_METHOD = "deal:payment_method"
    DEAL_DETAILS = "deal:details"
