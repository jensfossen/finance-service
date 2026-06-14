from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal
import json
import sqlite3
from typing import Protocol

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .models import (
    AccountListResponse,
    AccountRecord,
    AuditEvent,
    CreateTransactionRequest,
    SummaryGroupBy,
    SummaryLine,
    SummaryRequest,
    SummaryResponse,
    SummaryTotals,
    TransactionListResponse,
    TransactionRecord,
    TransactionStatus,
    UpdateTransactionRequest,
)


class FinanceRepository(Protocol):
    def list_accounts(self) -> AccountListResponse:
        ...

    def create_transaction(self, request: CreateTransactionRequest) -> tuple[TransactionRecord, AuditEvent]:
        ...

    def get_transaction(self, transaction_id: str) -> TransactionRecord | None:
        ...

    def list_transactions(
        self,
        account_id: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> TransactionListResponse:
        ...

    def update_transaction(
        self,
        transaction_id: str,
        request: UpdateTransactionRequest,
    ) -> tuple[TransactionRecord | None, AuditEvent | None]:
        ...

    def summarize(self, request: SummaryRequest) -> SummaryResponse:
        ...


class InMemoryFinanceRepository:
    def __init__(self) -> None:
        self._transactions: OrderedDict[str, TransactionRecord] = OrderedDict()

    def list_accounts(self) -> AccountListResponse:
        return AccountListResponse(items=[])

    def create_transaction(self, request: CreateTransactionRequest) -> tuple[TransactionRecord, AuditEvent]:
        transaction = TransactionRecord(
            transaction_id=f"txn_{len(self._transactions) + 1:06d}",
            account_id=request.account_id,
            effective_at=request.effective_at,
            amount=request.amount,
            currency=request.currency,
            direction=request.direction,
            category=request.category,
            merchant=request.merchant,
            description=request.description,
            external_ref=request.external_ref,
            tags=request.tags,
            status=TransactionStatus.posted,
            created_by=request.requested_by,
            updated_by=request.requested_by,
        )
        self._transactions[transaction.transaction_id] = transaction
        audit = AuditEvent(
            operation="create_transaction",
            entity_type="transaction",
            entity_id=transaction.transaction_id,
            actor=request.requested_by,
            after=transaction.model_dump(mode="json"),
        )
        return transaction, audit

    def get_transaction(self, transaction_id: str) -> TransactionRecord | None:
        transaction = self._transactions.get(transaction_id)
        if transaction is None:
            return None
        return deepcopy(transaction)

    def list_transactions(
        self,
        account_id: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> TransactionListResponse:
        items: list[TransactionRecord] = []
        for transaction in self._transactions.values():
            if account_id and transaction.account_id != account_id:
                continue
            if date_from and transaction.effective_at.isoformat() < date_from:
                continue
            if date_to and transaction.effective_at.isoformat() > date_to:
                continue
            items.append(deepcopy(transaction))
            if len(items) >= limit:
                break
        return TransactionListResponse(items=items)

    def update_transaction(
        self,
        transaction_id: str,
        request: UpdateTransactionRequest,
    ) -> tuple[TransactionRecord | None, AuditEvent | None]:
        current = self._transactions.get(transaction_id)
        if current is None:
            return None, None
        before = current.model_dump(mode="json")
        updates = request.changes.model_dump(exclude_none=True)
        updated = current.model_copy(update={**updates, "updated_by": request.requested_by})
        self._transactions[transaction_id] = updated
        audit = AuditEvent(
            operation="update_transaction",
            entity_type="transaction",
            entity_id=transaction_id,
            actor=request.requested_by,
            before=before,
            after=updated.model_dump(mode="json"),
            reason=request.reason,
        )
        return deepcopy(updated), audit

    def summarize(self, request: SummaryRequest) -> SummaryResponse:
        credits = Decimal("0.00")
        debits = Decimal("0.00")
        buckets: dict[str, Decimal] = {}
        for transaction in self._transactions.values():
            if transaction.account_id != request.account_id:
                continue
            if transaction.effective_at < request.date_from or transaction.effective_at > request.date_to:
                continue
            if not request.include_pending and transaction.status == TransactionStatus.pending:
                continue
            key = self._summary_key(transaction, request.group_by)
            signed = transaction.amount if transaction.direction.value == "credit" else -transaction.amount
            buckets[key] = buckets.get(key, Decimal("0.00")) + signed
            if transaction.direction.value == "credit":
                credits += transaction.amount
            else:
                debits += transaction.amount
        lines = [SummaryLine(key=key, amount=amount) for key, amount in sorted(buckets.items())]
        return SummaryResponse(
            account_id=request.account_id,
            date_from=request.date_from,
            date_to=request.date_to,
            totals=SummaryTotals(credits=credits, debits=debits, net=credits - debits),
            lines=lines,
        )

    @staticmethod
    def _summary_key(transaction: TransactionRecord, group_by: SummaryGroupBy) -> str:
        if group_by == SummaryGroupBy.day:
            return transaction.effective_at.isoformat()
        if group_by == SummaryGroupBy.merchant:
            return transaction.merchant or "unknown"
        return transaction.category


class SqliteFinanceRepository:
    def __init__(self, sqlite_path: str) -> None:
        self._sqlite_path = sqlite_path

    def list_accounts(self) -> AccountListResponse:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    account_id,
                    account_name,
                    account_type,
                    currency,
                    current_balance_cents,
                    last_transaction_date
                from v_account_current_balances
                order by account_id
                """
            ).fetchall()
        return AccountListResponse(
            items=[
                AccountRecord(
                    account_id=str(row["account_id"]),
                    account_name=row["account_name"],
                    account_type=row["account_type"],
                    currency=row["currency"],
                    current_balance=Decimal(row["current_balance_cents"]) / Decimal("100"),
                    last_transaction_date=row["last_transaction_date"],
                )
                for row in rows
            ]
        )

    def create_transaction(self, request: CreateTransactionRequest) -> tuple[TransactionRecord, AuditEvent]:
        account_id = self._resolve_account_id(request.account_id)
        category_id = self._resolve_category_id(request.category)
        direction = self._map_direction(request.direction.value)
        amount_cents = int((request.amount * 100).to_integral_value())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert into transactions (
                    account_id,
                    transaction_date,
                    posted_date,
                    description,
                    original_description,
                    merchant,
                    direction,
                    amount_cents,
                    status,
                    review_status,
                    external_transaction_id,
                    notes
                ) values (?, ?, ?, ?, ?, ?, ?, ?, 'cleared', 'unreviewed', ?, ?)
                """,
                (
                    account_id,
                    request.effective_at.isoformat(),
                    request.effective_at.isoformat(),
                    request.description or request.merchant or request.category,
                    request.description or request.merchant or request.category,
                    request.merchant,
                    direction,
                    amount_cents,
                    request.external_ref,
                    request.description,
                ),
            )
            transaction_id = int(cursor.lastrowid)
            conn.execute(
                """
                insert into transaction_splits (
                    transaction_id,
                    category_id,
                    memo,
                    amount_cents
                ) values (?, ?, ?, ?)
                """,
                (transaction_id, category_id, request.description, amount_cents),
            )
            conn.commit()
        transaction = self.get_transaction(str(transaction_id))
        if transaction is None:
            raise RuntimeError("transaction was created but could not be loaded")
        audit = AuditEvent(
            operation="create_transaction",
            entity_type="transaction",
            entity_id=transaction.transaction_id,
            actor=request.requested_by,
            after=transaction.model_dump(mode="json"),
        )
        return transaction, audit

    def get_transaction(self, transaction_id: str) -> TransactionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                    t.transaction_id as id,
                    t.account_id,
                    a.account_name,
                    t.transaction_date,
                    t.amount_cents,
                    t.direction,
                    t.status,
                    t.description,
                    t.merchant,
                    t.external_transaction_id,
                    t.notes,
                    t.created_at,
                    t.updated_at,
                    c.name as category
                from transactions t
                join accounts a on a.account_id = t.account_id
                left join transaction_splits ts on ts.transaction_id = t.transaction_id
                left join categories c on c.category_id = ts.category_id
                where t.transaction_id = ?
                order by ts.split_id
                limit 1
                """,
                (transaction_id,),
            ).fetchone()
        if row is None:
            return None
        return self._sqlite_row_to_transaction(row)

    def list_transactions(
        self,
        account_id: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> TransactionListResponse:
        clauses: list[str] = []
        params: list[object] = []
        if account_id:
            if account_id.isdigit():
                clauses.append("t.account_id = ?")
                params.append(int(account_id))
            else:
                clauses.append("a.account_name = ?")
                params.append(account_id)
        if date_from:
            clauses.append("t.transaction_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("t.transaction_date <= ?")
            params.append(date_to)
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(limit)
        sql = f"""
            select
                t.transaction_id as id,
                t.account_id,
                a.account_name,
                t.transaction_date,
                t.amount_cents,
                t.direction,
                t.status,
                t.description,
                t.merchant,
                t.external_transaction_id,
                t.notes,
                t.created_at,
                t.updated_at,
                c.name as category
            from transactions t
            join accounts a on a.account_id = t.account_id
            left join transaction_splits ts on ts.transaction_id = t.transaction_id
            left join categories c on c.category_id = ts.category_id
            {where_sql}
            group by t.transaction_id
            order by t.transaction_date desc, t.transaction_id desc
            limit ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return TransactionListResponse(items=[self._sqlite_row_to_transaction(row) for row in rows])

    def update_transaction(
        self,
        transaction_id: str,
        request: UpdateTransactionRequest,
    ) -> tuple[TransactionRecord | None, AuditEvent | None]:
        current = self.get_transaction(transaction_id)
        if current is None:
            return None, None
        changes = request.changes.model_dump(exclude_none=True)
        before = current.model_dump(mode="json")
        with self._connect() as conn:
            account_id = self._resolve_account_id(str(changes["account_id"])) if "account_id" in changes else current.account_id
            amount_cents = (
                int((Decimal(str(changes["amount"])) * 100).to_integral_value())
                if "amount" in changes
                else int((current.amount * 100).to_integral_value())
            )
            if (
                "account_id" in changes
                or "effective_at" in changes
                or "amount" in changes
                or "description" in changes
                or "merchant" in changes
                or "external_ref" in changes
            ):
                conn.execute(
                    """
                    update transactions
                    set
                        account_id = ?,
                        transaction_date = coalesce(?, transaction_date),
                        posted_date = coalesce(?, posted_date),
                        description = coalesce(?, description),
                        original_description = coalesce(?, original_description),
                        merchant = coalesce(?, merchant),
                        amount_cents = ?,
                        external_transaction_id = coalesce(?, external_transaction_id),
                        updated_at = CURRENT_TIMESTAMP,
                        notes = coalesce(?, notes)
                    where transaction_id = ?
                    """,
                    (
                        account_id,
                        changes.get("effective_at"),
                        changes.get("effective_at"),
                        changes.get("description"),
                        changes.get("description"),
                        changes.get("merchant"),
                        amount_cents,
                        changes.get("external_ref"),
                        request.reason,
                        transaction_id,
                    ),
                )
            if "category" in changes or "description" in changes:
                if "category" in changes:
                    category_id = self._resolve_category_id(str(changes["category"]))
                    conn.execute(
                        """
                        update transaction_splits
                        set category_id = ?
                        where transaction_id = ?
                        """,
                        (category_id, transaction_id),
                    )
                if "description" in changes:
                    conn.execute(
                        """
                        update transaction_splits
                        set
                            memo = coalesce(?, memo),
                            amount_cents = ?
                        where transaction_id = ?
                        """,
                        (changes["description"], amount_cents, transaction_id),
                    )
                elif "amount" in changes:
                    conn.execute(
                        """
                        update transaction_splits
                        set amount_cents = ?
                        where transaction_id = ?
                        """,
                        (amount_cents, transaction_id),
                    )
            conn.commit()
        updated = self.get_transaction(transaction_id)
        if updated is None:
            return None, None
        audit = AuditEvent(
            operation="update_transaction",
            entity_type="transaction",
            entity_id=str(transaction_id),
            actor=request.requested_by,
            before=before,
            after=updated.model_dump(mode="json"),
            reason=request.reason,
        )
        return updated, audit

    def summarize(self, request: SummaryRequest) -> SummaryResponse:
        account_key = int(request.account_id) if request.account_id.isdigit() else None
        with self._connect() as conn:
            if account_key is None:
                row = conn.execute(
                    "select account_id from accounts where account_name = ?",
                    (request.account_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"unknown account: {request.account_id}")
                account_key = int(row["account_id"])
            totals = conn.execute(
                """
                select
                    coalesce(sum(case when direction = 'inflow' then amount_cents else 0 end), 0) as inflow_cents,
                    coalesce(sum(case when direction = 'outflow' then amount_cents else 0 end), 0) as outflow_cents,
                    coalesce(sum(signed_amount_cents), 0) as net_cents
                from transactions
                where account_id = ?
                  and transaction_date >= ?
                  and transaction_date <= ?
                  and (? or status <> 'pending')
                """,
                (
                    account_key,
                    request.date_from.isoformat(),
                    request.date_to.isoformat(),
                    1 if request.include_pending else 0,
                ),
            ).fetchone()
            group_expr = {
                SummaryGroupBy.category: "coalesce(c.name, 'uncategorized')",
                SummaryGroupBy.merchant: "coalesce(t.merchant, 'unknown')",
                SummaryGroupBy.day: "t.transaction_date",
            }[request.group_by]
            rows = conn.execute(
                f"""
                select
                    {group_expr} as key,
                    coalesce(sum(case when t.direction = 'inflow' then t.amount_cents else -t.amount_cents end), 0) as signed_cents
                from transactions t
                left join transaction_splits ts on ts.transaction_id = t.transaction_id
                left join categories c on c.category_id = ts.category_id
                where t.account_id = ?
                  and t.transaction_date >= ?
                  and t.transaction_date <= ?
                  and (? or t.status <> 'pending')
                group by 1
                order by 1
                """,
                (
                    account_key,
                    request.date_from.isoformat(),
                    request.date_to.isoformat(),
                    1 if request.include_pending else 0,
                ),
            ).fetchall()
        return SummaryResponse(
            account_id=request.account_id,
            date_from=request.date_from,
            date_to=request.date_to,
            totals=SummaryTotals(
                credits=Decimal(totals["inflow_cents"]) / Decimal("100"),
                debits=Decimal(totals["outflow_cents"]) / Decimal("100"),
                net=Decimal(totals["net_cents"]) / Decimal("100"),
            ),
            lines=[
                SummaryLine(
                    key=str(row["key"]),
                    amount=Decimal(row["signed_cents"]) / Decimal("100"),
                )
                for row in rows
            ],
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _resolve_account_id(self, account_ref: str) -> int:
        with self._connect() as conn:
            if account_ref.isdigit():
                row = conn.execute(
                    "select account_id from accounts where account_id = ?",
                    (int(account_ref),),
                ).fetchone()
            else:
                row = conn.execute(
                    "select account_id from accounts where account_name = ?",
                    (account_ref,),
                ).fetchone()
        if row is None:
            raise RuntimeError(f"unknown account: {account_ref}")
        return int(row["account_id"])

    def _resolve_category_id(self, category_name: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "select category_id from categories where name = ?",
                (category_name,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"unknown category: {category_name}")
        return int(row["category_id"])

    @staticmethod
    def _map_direction(direction: str) -> str:
        return {"credit": "inflow", "debit": "outflow"}[direction]

    @staticmethod
    def _sqlite_row_to_transaction(row: sqlite3.Row) -> TransactionRecord:
        direction = "credit" if row["direction"] == "inflow" else "debit"
        payload = {
            "transaction_id": str(row["id"]),
            "account_id": str(row["account_id"]),
            "effective_at": row["transaction_date"],
            "amount": (Decimal(row["amount_cents"]) / Decimal("100")).quantize(Decimal("0.01")),
            "currency": "USD",
            "direction": direction,
            "category": row["category"] or "uncategorized",
            "merchant": row["merchant"],
            "description": row["description"],
            "external_ref": row["external_transaction_id"],
            "tags": [],
            "status": "posted" if row["status"] == "cleared" else "pending",
            "created_at": row["created_at"],
            "created_by": "finance-service",
            "updated_at": row["updated_at"],
            "updated_by": "finance-service",
        }
        return TransactionRecord.model_validate(payload)


class PostgresFinanceRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_accounts(self) -> AccountListResponse:
        with connect(self._database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                select
                    account_id,
                    account_name,
                    account_type,
                    currency,
                    current_balance_cents,
                    last_transaction_date
                from finance.v_account_current_balances
                order by account_id
                """
            ).fetchall()
        return AccountListResponse(
            items=[
                AccountRecord(
                    account_id=str(row["account_id"]),
                    account_name=row["account_name"],
                    account_type=row["account_type"],
                    currency=row["currency"],
                    current_balance=Decimal(row["current_balance_cents"]) / Decimal("100"),
                    last_transaction_date=row["last_transaction_date"],
                )
                for row in rows
            ]
        )

    def create_transaction(self, request: CreateTransactionRequest) -> tuple[TransactionRecord, AuditEvent]:
        payload = request.model_dump(mode="json")
        with connect(self._database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "select * from finance.create_transaction(%s::jsonb)",
                (Json(payload),),
            ).fetchone()
        if row is None:
            raise RuntimeError("create_transaction returned no row")
        transaction = self.get_transaction(str(row["transaction_id"]))
        if transaction is None:
            raise RuntimeError("transaction was created but could not be loaded")
        audit = AuditEvent(
            audit_id=str(row["audit_id"]),
            operation="create_transaction",
            entity_type="transaction",
            entity_id=transaction.transaction_id,
            actor=request.requested_by,
            after=transaction.model_dump(mode="json"),
        )
        return transaction, audit

    def get_transaction(self, transaction_id: str) -> TransactionRecord | None:
        with connect(self._database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                select *
                from finance.v_transaction_history
                where id = %s
                """,
                (transaction_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_transaction(row)

    def list_transactions(
        self,
        account_id: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> TransactionListResponse:
        clauses: list[str] = []
        params: list[object] = []
        if account_id:
            clauses.append("account_id = %s")
            params.append(account_id)
        if date_from:
            clauses.append("effective_at >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("effective_at <= %s")
            params.append(date_to)
        where_sql = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(limit)
        sql = f"""
            select *
            from finance.v_transaction_history
            {where_sql}
            order by effective_at desc, id desc
            limit %s
        """
        with connect(self._database_url, row_factory=dict_row) as conn:
            rows = conn.execute(sql, params).fetchall()
        return TransactionListResponse(items=[self._row_to_transaction(row) for row in rows])

    def update_transaction(
        self,
        transaction_id: str,
        request: UpdateTransactionRequest,
    ) -> tuple[TransactionRecord | None, AuditEvent | None]:
        payload = request.model_dump(mode="json")
        with connect(self._database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "select * from finance.update_transaction(%s, %s::jsonb)",
                (transaction_id, Json(payload)),
            ).fetchone()
        if row is None:
            return None, None
        transaction = self.get_transaction(transaction_id)
        if transaction is None:
            return None, None
        audit = AuditEvent(
            audit_id=str(row["audit_id"]),
            operation="update_transaction",
            entity_type="transaction",
            entity_id=transaction_id,
            actor=request.requested_by,
            reason=request.reason,
            after=transaction.model_dump(mode="json"),
        )
        return transaction, audit

    def summarize(self, request: SummaryRequest) -> SummaryResponse:
        payload = request.model_dump(mode="json")
        with connect(self._database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "select * from finance.summarize_transactions(%s::jsonb)",
                (Json(payload),),
            ).fetchone()
        if row is None:
            raise RuntimeError("summarize_transactions returned no row")
        totals = row["totals"]
        lines = row["lines"]
        if isinstance(totals, str):
            totals = json.loads(totals)
        if isinstance(lines, str):
            lines = json.loads(lines)
        return SummaryResponse(
            account_id=request.account_id,
            date_from=request.date_from,
            date_to=request.date_to,
            totals=SummaryTotals(**totals),
            lines=[SummaryLine(**line) for line in lines],
        )

    @staticmethod
    def _row_to_transaction(row: dict[str, object]) -> TransactionRecord:
        payload = {
            "transaction_id": row["id"],
            "account_id": row["account_id"],
            "effective_at": row["effective_at"],
            "amount": row["amount"],
            "currency": row["currency"],
            "direction": row["direction"],
            "category": row["category"],
            "merchant": row.get("merchant"),
            "description": row.get("description"),
            "external_ref": row.get("external_ref"),
            "tags": row.get("tags") or [],
            "status": row["status"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }
        return TransactionRecord.model_validate(payload)


def build_repository(database_url: str | None, sqlite_path: str | None = None) -> FinanceRepository:
    if database_url:
        return PostgresFinanceRepository(database_url)
    if sqlite_path:
        return SqliteFinanceRepository(sqlite_path)
    return InMemoryFinanceRepository()
