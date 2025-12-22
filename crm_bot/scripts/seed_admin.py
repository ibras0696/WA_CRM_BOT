"""Создаёт администратора из переменной окружения ADMIN_PHONE."""

from crm_bot.config import settings
from crm_bot.core.db import db_session
from crm_bot.core.models import User, UserRole


def main() -> None:
    if not settings.admin_phones:
        print("ADMIN_PHONE(S) не указаны.")
        return

    with db_session() as session:
        for phone in settings.admin_phones:
            user = (
                session.query(User)
                .filter(User.phone == phone)
                .one_or_none()
            )
            if user:
                user.role = UserRole.ADMIN
                user.is_active = True
                session.flush()
                print(f"Админ уже существует: {user.phone}")
                continue

            user = User(
                phone=phone,
                role=UserRole.ADMIN,
                is_active=True,
                name="Admin",
            )
            session.add(user)
            session.flush()
            print(f"Админ создан: {user.phone}")


if __name__ == "__main__":
    main()
