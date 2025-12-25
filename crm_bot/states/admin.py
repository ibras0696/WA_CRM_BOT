from enum import Enum


class AdminAddManagerStates(str, Enum):
    """FSM для добавления нового менеджера."""

    SENDER = "admin_add_manager_sender"


class AdminDeleteManagerStates(str, Enum):
    """FSM для отключения менеджера."""

    SENDER = "admin_delete_manager_sender"


class AdminAnalyticsStates(str, Enum):
    """FSM для аналитических запросов."""

    MANAGER_REPORT = "admin_analytics_manager_phone"


class AdminAdjustBalanceStates(str, Enum):
    """FSM корректировки баланса сотрудника."""

    WORKER_PHONE = "admin_adjust_balance_worker_phone"
    BALANCE_KIND = "admin_adjust_balance_kind"
    DELTA = "admin_adjust_balance_delta"


class AdminDeleteDealStates(str, Enum):
    """FSM мягкого удаления операции."""

    DEAL_ID = "admin_delete_deal_id"


class AdminFullReportStates(str, Enum):
    """FSM полного отчёта (произвольный диапазон)."""

    CUSTOM_RANGE = "admin_full_report_custom_range"
