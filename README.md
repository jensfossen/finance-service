# Finance Service

Starter service layer for Hermes-managed finance operations.

This service is intended to sit between Hermes and Postgres so the agent never
gets raw write access to ledger tables.

## Scope

This scaffold provides:

- strict request and response schemas
- confirmation-aware write operations
- a repository boundary for future Postgres integration
- a Postgres repository selected by `FINANCE_DATABASE_URL`
- an in-memory repository for local development and tests
- starter SQL for the eventual Postgres layer

## Endpoints

- `GET /healthz`
- `GET /accounts`
- `GET /transactions`
- `GET /transactions/{transaction_id}`
- `POST /transactions`
- `PATCH /transactions/{transaction_id}`
- `POST /transactions/summary`

## Run

```bash
uvicorn finance_service.app:app --app-dir src --reload
```

## CLI Client

The included CLI is a simple bridge Hermes can call safely:

```bash
python -m finance_service.client list-accounts
python -m finance_service.client list-transactions --account-id kids_checking_emma
python -m finance_service.client summarize --json '{"account_id":"kids_checking_emma","date_from":"2026-06-01","date_to":"2026-06-30"}'
```

Set `FINANCE_SERVICE_URL` if the API is not on `http://127.0.0.1:8000`.

## Hermes Integration Shape

Hermes should call the CLI or HTTP API with structured payloads only. Good examples:

```bash
python -m finance_service.client create-transaction --json '{
  "account_id":"1",
  "effective_at":"2026-06-10",
  "amount":"25.00",
  "currency":"USD",
  "direction":"credit",
  "category":"General Deposit",
  "merchant":"Parent transfer",
  "description":"Weekly allowance",
  "tags":["emma","allowance"],
  "requested_by":"telegram:8627150253"
}'
```

For risky edits, send the first request without `confirmation_token`, inspect the response, then resend with the returned token. Example:

```bash
python -m finance_service.client update-transaction 133 --json '{
  "changes":{"amount":"3.00"},
  "reason":"Parent corrected purchase amount",
  "requested_by":"telegram:8627150253"
}'
```

If the response includes `"confirmation_required": true`, resend:

```bash
python -m finance_service.client update-transaction 133 --json '{
  "changes":{"amount":"3.00"},
  "reason":"Parent corrected purchase amount",
  "requested_by":"telegram:8627150253",
  "confirmation_token":"confirm-update"
}'
```

## Next Steps

1. Replace the in-memory repository with a Postgres-backed implementation.
2. Route writes through stored procedures only.
3. Add auth between Hermes and this service.
4. Add explicit confirmation tokens for balance-affecting writes.

## Configuration

Environment variables:

- `FINANCE_DATABASE_URL`
  When set, the service uses Postgres. When absent, it uses the in-memory repository.
- `FINANCE_SQLITE_PATH`
  When `FINANCE_DATABASE_URL` is unset and this path is set, the service uses the real local SQLite finance database.
- `FINANCE_REQUIRE_CONFIRMATION_OVER`
  Optional decimal threshold for high-value create confirmations. Default: `1000.00`
