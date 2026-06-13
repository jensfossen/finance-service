from __future__ import annotations

from fastapi import FastAPI, Query

from .config import load_settings
from .models import (
    AccountListResponse,
    CreateTransactionRequest,
    MutationResult,
    SummaryRequest,
    SummaryResponse,
    TransactionListResponse,
    TransactionRecord,
    UpdateTransactionRequest,
)
from .repository import build_repository
from .service import FinanceService


app = FastAPI(title="Finance Service", version="0.1.0")
settings = load_settings()
service = FinanceService(
    build_repository(settings.database_url, settings.sqlite_path),
    risky_create_amount=settings.require_confirmation_over,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/accounts", response_model=AccountListResponse)
def list_accounts() -> AccountListResponse:
    return service.list_accounts()


@app.get("/transactions", response_model=TransactionListResponse)
def list_transactions(
    account_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> TransactionListResponse:
    return service.list_transactions(account_id, date_from, date_to, limit)


@app.get("/transactions/{transaction_id}", response_model=TransactionRecord)
def get_transaction(transaction_id: str) -> TransactionRecord:
    return service.get_transaction(transaction_id)


@app.post("/transactions", response_model=MutationResult, status_code=201)
def create_transaction(request: CreateTransactionRequest) -> MutationResult:
    return service.create_transaction(request)


@app.patch("/transactions/{transaction_id}", response_model=MutationResult)
def update_transaction(transaction_id: str, request: UpdateTransactionRequest) -> MutationResult:
    return service.update_transaction(transaction_id, request)


@app.post("/transactions/summary", response_model=SummaryResponse)
def summarize_transactions(request: SummaryRequest) -> SummaryResponse:
    return service.summarize(request)
