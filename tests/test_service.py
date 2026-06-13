from datetime import date
from decimal import Decimal
from pathlib import Path
import shutil
import tempfile

from finance_service.models import CreateTransactionRequest, SummaryRequest, UpdateTransactionRequest
from finance_service.repository import (
    InMemoryFinanceRepository,
    PostgresFinanceRepository,
    SqliteFinanceRepository,
    build_repository,
)
from finance_service.service import FinanceService


def test_create_and_summarize_transaction() -> None:
    service = FinanceService(InMemoryFinanceRepository())
    result = service.create_transaction(
        CreateTransactionRequest(
            account_id="kids_checking_emma",
            effective_at=date(2026, 6, 10),
            amount=Decimal("25.00"),
            currency="usd",
            direction="credit",
            category="allowance",
            merchant="parent_transfer",
            description="Weekly allowance",
            tags=["emma"],
            requested_by="telegram:8627150253",
        )
    )
    assert result.ok is True
    summary = service.summarize(
        SummaryRequest(
            account_id="kids_checking_emma",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 30),
        )
    )
    assert summary.totals.credits == Decimal("25.00")
    assert summary.totals.net == Decimal("25.00")


def test_update_transaction_description() -> None:
    service = FinanceService(InMemoryFinanceRepository())
    created = service.create_transaction(
        CreateTransactionRequest(
            account_id="kids_checking_emma",
            effective_at=date(2026, 6, 10),
            amount=Decimal("12.00"),
            currency="USD",
            direction="debit",
            category="books",
            merchant="bookstore",
            description="Old description",
            tags=["emma"],
            requested_by="telegram:8627150253",
        )
    )
    updated = service.update_transaction(
        created.transaction_id,
        UpdateTransactionRequest(
            changes={"description": "Summer reading purchase"},
            reason="Parent corrected description",
            requested_by="telegram:8627150253",
        ),
    )
    assert updated.ok is True


def test_large_create_requires_confirmation() -> None:
    service = FinanceService(
        InMemoryFinanceRepository(),
        risky_create_amount=Decimal("100.00"),
    )
    result = service.create_transaction(
        CreateTransactionRequest(
            account_id="kids_checking_emma",
            effective_at=date(2026, 6, 10),
            amount=Decimal("125.00"),
            currency="USD",
            direction="credit",
            category="gift",
            merchant="grandparents",
            description="Birthday gift",
            tags=["emma"],
            requested_by="telegram:8627150253",
        )
    )
    assert result.confirmation_required is True
    assert result.confirmation_token == "confirm-create"


def test_build_repository_uses_memory_without_database_url() -> None:
    repository = build_repository(None)
    assert isinstance(repository, InMemoryFinanceRepository)


def test_build_repository_uses_postgres_with_database_url() -> None:
    repository = build_repository("postgresql://example")
    assert isinstance(repository, PostgresFinanceRepository)


def test_build_repository_uses_sqlite_with_sqlite_path() -> None:
    repository = build_repository(None, "/tmp/finance.sqlite")
    assert isinstance(repository, SqliteFinanceRepository)


def test_list_accounts_from_sqlite_repository() -> None:
    repository = SqliteFinanceRepository("/Users/jensfossen-macmini/Documents/Finance/data/finance.sqlite")
    result = repository.list_accounts()
    assert result.ok is True
    assert any(item.account_name == "Deakin" for item in result.items)


def test_sqlite_repository_reads_real_schema() -> None:
    db_path = Path("/Users/jensfossen-macmini/Documents/Finance/data/finance.sqlite")
    repository = SqliteFinanceRepository(str(db_path))
    result = repository.list_transactions("Deakin", "2024-08-01", "2026-12-31", 5)
    assert result.ok is True
    assert len(result.items) >= 1


def test_sqlite_repository_create_and_update_on_temp_copy() -> None:
    source = Path("/Users/jensfossen-macmini/Documents/Finance/data/finance.sqlite")
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "finance.sqlite"
        shutil.copy2(source, target)
        service = FinanceService(SqliteFinanceRepository(str(target)))
        created = service.create_transaction(
            CreateTransactionRequest(
                account_id="Deakin",
                effective_at=date(2026, 6, 11),
                amount=Decimal("12.34"),
                currency="USD",
                direction="credit",
                category="General Deposit",
                merchant="Parent Transfer",
                description="Test deposit",
                tags=[],
                requested_by="test-suite",
            )
        )
        assert created.ok is True
        updated = service.update_transaction(
            created.transaction_id,
            UpdateTransactionRequest(
                changes={"description": "Updated test deposit", "amount": "13.34"},
                reason="test update",
                requested_by="test-suite",
                confirmation_token="confirm-update",
            ),
        )
        assert updated.ok is True
