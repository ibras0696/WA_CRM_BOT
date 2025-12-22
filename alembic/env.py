from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

import sys
from pathlib import Path

# 👇 добавляем корень проекта в PYTHONPATH
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from crm_bot.config import settings
from crm_bot.core.models import Base

config = context.config

# логирование
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 👇 Alembic будет смотреть сюда
target_metadata = Base.metadata


def get_url():
    return settings.database_url


def run_migrations_offline():
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        {
            "sqlalchemy.url": get_url(),
        },
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
