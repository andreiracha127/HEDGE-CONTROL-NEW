from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app import models
from app.core.database import get_database_url
from app.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Postgres-only: make alembic_version.version_num wide enough for this project's
        # descriptive revision IDs (longest today is "003_create_hedge_order_linkages_table"
        # at 37 chars). SQLite tests recreate schema fresh, so this is a no-op there.
        #
        # Two cases must be handled:
        #   1. Fresh DB — table does not exist. CREATE TABLE with VARCHAR(128).
        #   2. Already-initialized DB — table exists with Alembic's default VARCHAR(32).
        #      CREATE TABLE IF NOT EXISTS is a no-op here, so we need an explicit ALTER.
        # Codex adversarial review 2026-05-22 [high] — without (2), partially migrated
        # environments still fail when Alembic tries to stamp a long revision id.
        if connection.dialect.name == "postgresql":
            version_column = connection.execute(
                text(
                    "SELECT character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'alembic_version' "
                    "  AND column_name = 'version_num' "
                    "  AND table_schema = current_schema()"
                )
            ).mappings().first()

            if version_column is None:
                # Case 1: fresh DB. Use IF NOT EXISTS to survive the race window
                # between the information_schema probe above and this CREATE — two
                # Alembic processes initialising the same empty schema in parallel
                # (e.g. parallel deploy workers) would otherwise crash here.
                connection.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS alembic_version ("
                        "version_num VARCHAR(128) NOT NULL, "
                        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                        ")"
                    )
                )
            else:
                existing_len = version_column["character_maximum_length"]
                if existing_len is not None and existing_len < 128:
                    # Case 2: pre-existing narrow column. Widen in place.
                    connection.execute(
                        text(
                            "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
                        )
                    )
                # else: column already wide enough, or unbounded TEXT/VARCHAR — no-op.
            connection.commit()

        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
