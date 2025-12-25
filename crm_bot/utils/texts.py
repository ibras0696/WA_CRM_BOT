"""Тексты ответов бота, вынесенные отдельно от логики."""

from decimal import Decimal
from typing import Iterable

# from .services import DealSummary
# from .utils import format_money

# CANCEL_MESSAGE = "Действие отменено. Возвращаю вас в меню."
# EMPTY_DEALS_MESSAGE = "Операций пока нет. Создайте первую операцию через меню."
# ASK_CLIENT_NAME = "Напиши имя клиента"
# ASK_CLIENT_PHONE = "Укажи телефон клиента"
# ASK_DEAL_AMOUNT = "Сумма операции в рублях?"
# ASK_DEAL_TERM = "За какой срок рассрочка (в месяцах)?"
# PAYMENT_SELECT_PROMPT = "Выберите операцию для оплаты"
# PAYMENT_AMOUNT_PROMPT = "Укажи сумму платежа в рублях"
# FALLBACK_MESSAGE = "Привет! Чтобы начать, выбери действие в меню."
# ADD_MEMBER_USAGE = (
#     "Напиши: 'добавить сотрудника <телефон> <Имя>'. Пример: "
#     "добавить сотрудника 79991234567 Иван"
# )


# def deal_saved_text(summary: DealSummary) -> str:
#     """Составляет итоговое сообщение после сохранения операции."""
#     return (
#         "Операция сохранена:\n"
#         f"#{summary.id} {summary.client}\n"
#         f"Сумма: {format_money(summary.total_amount)}\n"
#         f"Платежей: {format_money(summary.paid)}\n"
#         f"Долг: {format_money(summary.debt)}\n"
#         f"Статус: {summary.status}"
#     )


# def payment_saved_text(amount: Decimal, summary: DealSummary) -> str:
#     """Генерирует уведомление о приёме платежа."""
#     return (
#         f"Платёж {format_money(amount)} за операцию #{summary.id} принят.\n"
#         f"Оплачено {format_money(summary.paid)} из {format_money(summary.total_amount)}\n"
#         f"Остаток: {format_money(summary.debt)}\n"
#         f"Статус: {summary.status}"
#     )


# def my_deals_text(deals: Iterable[DealSummary]) -> str:
#     """Собирает краткий список операций для пользователя."""
#     if not deals:
#         return EMPTY_DEALS_MESSAGE
#     lines = [
#         f"#{item.id} {item.client} — {item.status} (долг {format_money(item.debt)})"
#         for item in deals
#     ]
#     return "Последние операции:\n" + "\n".join(lines)


# def analytics_text(stats: dict[str, Decimal]) -> str:
#     """Формирует текст аналитики по компании."""
#     lines = [
#         f"Оборот: {format_money(stats['turnover'])}",
#         f"Доход: {format_money(stats['income'])}",
#         f"Долг: {format_money(stats['debt'])}",
#     ]
#     workers = stats.get("by_worker")
#     if workers:
#         lines.append("По сотрудникам:")
#         lines.extend(f"{phone}: {format_money(amount)}" for phone, amount in workers)
#     return "\n".join(lines)


# def members_text(members: Iterable) -> str:
#     """Готовит текст со списком сотрудников."""
#     if not members:
#         return "Сотрудников пока нет."
#     lines = [
#         f"{membership.user.phone} — {membership.role} ({'активен' if membership.is_active else 'отключён'})"
#         for membership in members
#     ]
#     return "Сотрудники:\n" + "\n".join(lines)


# def member_added_text(phone: str) -> str:
#     """Сообщение об успешном добавлении сотрудника."""
#     return f"Сотрудник с номером {phone} активирован и может пользоваться ботом."


# def member_disabled_text(phone: str) -> str:
#     """Сообщает об отключении сотрудника."""
#     return f"Доступ для номера {phone} отключён."


# def member_not_found_text(phone: str) -> str:
#     """Сообщает, что сотрудник не найден."""
#     return f"Сотрудник с номером {phone} не найден или уже отключён."
