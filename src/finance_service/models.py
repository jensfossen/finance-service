from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Direction(str, Enum):
    debit = "debit"
    credit = "credit"


class TransactionStatus(str, Enum):
    posted = "posted"
    pending = "pending"
    reversed = "reversed"


class SummaryGroupBy(str, Enum):
    category = "category"
    merchant = "merchant"
    day = "day"


class TransactionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=128)
    effective_at: date
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    direction: Direction
    category: str = Field(min_length=1, max_length=64)
    merchant: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    external_ref: str | None = Field(default=None, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=25)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class CreateTransactionRequest(TransactionBase):
    requested_by: str = Field(min_length=1, max_length=128)
    confirmation_token: str | None = Field(default=None, max_length=128)


class TransactionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str | None = Field(default=None, min_length=1, max_length=128)
    effective_at: date | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    merchant: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    external_ref: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = Field(default=None, max_length=25)


class UpdateTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: TransactionPatch
    reason: str = Field(min_length=1, max_length=512)
    requested_by: str = Field(min_length=1, max_length=128)
    confirmation_token: str | None = Field(default=None, max_length=128)


class TransactionRecord(TransactionBase):
    transaction_id: str
    status: TransactionStatus = TransactionStatus.posted
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str
    updated_at: datetime = Field(default_factory=utc_now)
    updated_by: str


class MutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    transaction_id: str
    status: TransactionStatus
    balance_after: Decimal | None = None
    currency: str
    audit_id: str
    confirmation_required: bool = False
    confirmation_token: str | None = None


class TransactionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    items: list[TransactionRecord]
    next_cursor: str | None = None


class AccountRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    account_name: str
    account_type: str
    currency: str
    current_balance: Decimal | None = None
    last_transaction_date: date | None = None


class AccountListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    items: list[AccountRecord]


class SummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=128)
    date_from: date
    date_to: date
    group_by: SummaryGroupBy = SummaryGroupBy.category
    include_pending: bool = False


class SummaryLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    amount: Decimal


class SummaryTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credits: Decimal
    debits: Decimal
    net: Decimal


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    account_id: str
    date_from: date
    date_to: date
    totals: SummaryTotals
    lines: list[SummaryLine]


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: f"aud_{uuid4().hex}")
    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex}")
    operation: str
    entity_type: str
    entity_id: str
    actor: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
