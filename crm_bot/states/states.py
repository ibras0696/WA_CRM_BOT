"""Состояния FSM-процессов для бота."""

from whatsapp_chatbot_python.manager.state import BaseStates


class States(BaseStates):
    """Определяет названия шагов пользователя в процессе ввода операций/платежей."""

    OPEN_SHIFT_CASH = "shift:opening_cash"
    OPEN_SHIFT_BANK = "shift:opening_bank"
    CLOSE_SHIFT_CASH = "shift:closing_cash"
    CLOSE_SHIFT_BANK = "shift:closing_bank"
    DEAL_AMOUNT = "deal:amount"
    DEAL_PAYMENT_METHOD = "deal:payment_method"
    DEAL_DETAILS = "deal:details"
    INSTALLMENT_PRICE = "installment:price"
    INSTALLMENT_PERCENT = "installment:percent"
    INSTALLMENT_TERM = "installment:term"
    INSTALLMENT_DOWN_PAYMENT = "installment:down_payment"
    INSTALLMENT_PAYMENT_METHOD = "installment:payment_method"
