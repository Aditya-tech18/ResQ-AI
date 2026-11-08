"""Safely enforce one active exception per merchant/shipment.

Supports SQLite and PostgreSQL.
Does not silently delete or modify duplicate records.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text

INDEX_NAME = "uq_exception_one_active_per_shipment"

ACTIVE_CONDITION = "status NOT IN ('resolved', 'cancelled')"


def main() -> None:
    default_db = "sqlite:///" + str(Path("data/dispatchresolve_dev.db").resolve())

    database_url = os.getenv(
        "DISPATCH_DATABASE_URL",
        default_db,
    )

    engine = create_engine(database_url)

    if engine.dialect.name not in {
        "sqlite",
        "postgresql",
    }:
        raise RuntimeError("Unsupported database dialect")

    with engine.begin() as connection:
        duplicates = connection.execute(
            text(
                """
                SELECT
                    merchant_id,
                    shipment_id,
                    COUNT(*) AS active_count
                FROM exception_cases
                WHERE status NOT IN ('resolved', 'cancelled')
                GROUP BY merchant_id, shipment_id
                HAVING COUNT(*) > 1
                """
            )
        ).all()

        if duplicates:
            print("ERROR: Existing active duplicates found")
            for row in duplicates:
                print(
                    "merchant=",
                    row[0],
                    "shipment=",
                    row[1],
                    "count=",
                    row[2],
                )
            raise SystemExit("Resolve duplicates before creating index.")

        connection.execute(
            text(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                {INDEX_NAME}
                ON exception_cases (
                    merchant_id,
                    shipment_id
                )
                WHERE {ACTIVE_CONDITION}
                """
            )
        )

        print("PASS: Unique active exception index ensured")

    engine.dispose()


if __name__ == "__main__":
    main()
