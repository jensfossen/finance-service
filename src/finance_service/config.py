from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    sqlite_path: str | None
    require_confirmation_over: Decimal


def load_settings() -> Settings:
    raw_threshold = os.getenv("FINANCE_REQUIRE_CONFIRMATION_OVER", "1000.00").strip()
    try:
        threshold = Decimal(raw_threshold)
    except InvalidOperation as exc:
        raise ValueError(
            "FINANCE_REQUIRE_CONFIRMATION_OVER must be a valid decimal"
        ) from exc
    database_url = os.getenv("FINANCE_DATABASE_URL", "").strip() or None
    sqlite_path = os.getenv("FINANCE_SQLITE_PATH", "").strip() or None
    return Settings(
        database_url=database_url,
        sqlite_path=sqlite_path,
        require_confirmation_over=threshold,
    )
