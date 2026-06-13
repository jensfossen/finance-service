from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status

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
from .repository import FinanceRepository


RISKY_EDIT_FIELDS = {"account_id", "effective_at", "amount"}


class FinanceService:
    def __init__(
        self,
        repository: FinanceRepository,
        *,
        risky_create_amount: Decimal = Decimal("1000.00"),
    ) -> None:
        self._repository = repository
        self._risky_create_amount = risky_create_amount

    def list_transactions(
        self,
        account_id: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> TransactionListResponse:
        return self._repository.list_transactions(account_id, date_from, date_to, limit)

    def list_accounts(self) -> AccountListResponse:
        return self._repository.list_accounts()

    def get_transaction(self, transaction_id: str) -> TransactionRecord:
        transaction = self._repository.get_transaction(transaction_id)
        if transaction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found")
        return transaction

    def create_transaction(self, request: CreateTransactionRequest) -> MutationResult:
        confirmation_required = request.amount >= self._risky_create_amount
        if confirmation_required and not request.confirmation_token:
            return MutationResult(
                transaction_id="pending",
                status="pending",
                currency=request.currency,
                audit_id="pending",
                confirmation_required=True,
                confirmation_token="confirm-create",
            )
        transaction, audit = self._repository.create_transaction(request)
        return MutationResult(
            transaction_id=transaction.transaction_id,
            status=transaction.status,
            currency=transaction.currency,
            audit_id=audit.audit_id,
        )

    def update_transaction(self, transaction_id: str, request: UpdateTransactionRequest) -> MutationResult:
        confirmation_required = bool(RISKY_EDIT_FIELDS.intersection(request.changes.model_dump(exclude_none=True)))
        if confirmation_required and not request.confirmation_token:
            transaction = self.get_transaction(transaction_id)
            return MutationResult(
                transaction_id=transaction.transaction_id,
                status=transaction.status,
                currency=transaction.currency,
                audit_id="pending",
                confirmation_required=True,
                confirmation_token="confirm-update",
            )
        transaction, audit = self._repository.update_transaction(transaction_id, request)
        if transaction is None or audit is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found")
        return MutationResult(
            transaction_id=transaction.transaction_id,
            status=transaction.status,
            currency=transaction.currency,
            audit_id=audit.audit_id,
        )

    def summarize(self, request: SummaryRequest) -> SummaryResponse:
        return self._repository.summarize(request)
