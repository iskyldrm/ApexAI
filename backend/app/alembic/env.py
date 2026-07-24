"""Alembic environment configuration.

Imports all SQLModel models so their tables register with `SQLModel.metadata`.
Run migrations with:
    cd backend && uv run alembic upgrade head
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app.config import get_settings

# Import all models so they register with SQLModel.metadata
# (Phase 1 task 8-22 will populate these)
# from app.models.platform_admin import PlatformAdmin  # noqa: F401
# from app.models.user import User  # noqa: F401
# from app.models.org import Org  # noqa: F401
# from app.models.team import Team  # noqa: F401
# from app.models.membership import OrgMembership, TeamMembership  # noqa: F401
# from app.models.invitation import Invitation  # noqa: F401
# from app.models.api_key import ApiKey  # noqa: F401
# from app.models.integration import IntegrationCredential  # noqa: F401
# from app.models.audit_log import AuditLog  # noqa: F401
# from app.models.setting import Setting  # noqa: F401
# from app.models.token_usage import TokenUsage  # noqa: F401
# from app.models.auth_token import (  # noqa: F401
#     PasswordResetToken,
#     EmailVerificationToken,
#     RefreshToken,
# )

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Alembic doesn't speak async URLs; strip the async driver prefix
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+psycopg", ""))

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with a live DB connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
