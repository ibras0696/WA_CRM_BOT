"""Закрытие всех активных смен (вызывать по расписанию)."""

from crm_bot.services import shifts


def main() -> None:
    closed = shifts.close_open_shifts()
    print(f"Закрыто смен: {closed}")


if __name__ == "__main__":
    main()
