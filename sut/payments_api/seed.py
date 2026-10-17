"""Drop, recreate and load the database with deterministic data.

Usage: python -m payments_api.seed  (DATABASE_URL and the optional SEED_* variables)
"""

import time

from sqlalchemy import create_engine

from payments_api import seed_data
from payments_api.config import Settings
from payments_api.models import Base


def seed(database_url: str, config: seed_data.SeedConfig) -> None:
    engine = create_engine(database_url)
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            cursor = connection.connection.driver_connection.cursor()
            with cursor.copy("COPY merchants (id, name, category) FROM STDIN") as copy:
                for row in seed_data.merchants(config):
                    copy.write_row(row)
            with cursor.copy(
                "COPY accounts (id, owner_name, currency, balance_cents) FROM STDIN"
            ) as copy:
                for row in seed_data.accounts(config):
                    copy.write_row(row)
            with cursor.copy(
                "COPY payments (account_id, merchant_id, amount_cents, currency, status,"
                " created_at) FROM STDIN"
            ) as copy:
                for row in seed_data.payments(config):
                    copy.write_row(row)
        # Fresh statistics, so query plans do not depend on when autovacuum last ran.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("ANALYZE")
    finally:
        engine.dispose()


def main() -> None:
    settings = Settings.from_env()
    config = seed_data.SeedConfig.from_env()
    started = time.perf_counter()
    seed(settings.database_url, config)
    elapsed = time.perf_counter() - started
    print(f"seeded {config} in {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
