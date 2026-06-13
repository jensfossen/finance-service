create schema if not exists finance;

create table if not exists finance.accounts (
    id text primary key,
    name text not null,
    currency char(3) not null,
    created_at timestamptz not null default now()
);

create table if not exists finance.transactions (
    id text primary key,
    account_id text not null references finance.accounts(id),
    effective_at date not null,
    posted_at timestamptz not null default now(),
    amount numeric(12,2) not null check (amount > 0),
    currency char(3) not null,
    direction text not null check (direction in ('debit', 'credit')),
    category text not null,
    merchant text,
    description text,
    external_ref text,
    status text not null default 'posted' check (status in ('posted', 'pending', 'reversed')),
    reversal_of_transaction_id text references finance.transactions(id),
    created_at timestamptz not null default now(),
    created_by text not null,
    updated_at timestamptz not null default now(),
    updated_by text not null
);

create table if not exists finance.transaction_revisions (
    id bigserial primary key,
    transaction_id text not null references finance.transactions(id),
    revision_number integer not null,
    before_json jsonb,
    after_json jsonb not null,
    reason text,
    changed_at timestamptz not null default now(),
    changed_by text not null
);

create table if not exists finance.audit_events (
    id text primary key,
    request_id text not null,
    operation text not null,
    entity_type text not null,
    entity_id text not null,
    actor text not null,
    result text not null default 'ok',
    payload_json jsonb,
    created_at timestamptz not null default now()
);

create or replace view finance.v_transaction_history as
select
    t.id,
    t.account_id,
    t.effective_at,
    t.posted_at,
    t.amount,
    t.currency,
    t.direction,
    t.category,
    t.merchant,
    t.description,
    t.external_ref,
    t.status,
    t.created_at,
    t.created_by,
    t.updated_at,
    t.updated_by
from finance.transactions t;
