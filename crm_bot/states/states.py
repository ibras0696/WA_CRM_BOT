"""Состояния FSM-процессов для бота."""

from whatsapp_chatbot_python.manager.state import BaseStates


class States(BaseStates):
    """Определяет названия шагов пользователя в процессе ввода сделок/платежей."""

    OPEN_SHIFT_AMOUNT = "shift:opening_balance"
    DEAL_CLIENT_NAME = "deal:client_name"
    DEAL_CLIENT_PHONE = "deal:client_phone"
    DEAL_AMOUNT = "deal:amount"
