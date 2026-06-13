create role finance_reader noinherit;
create role finance_writer noinherit;

grant usage on schema finance to finance_reader, finance_writer;
grant select on finance.v_transaction_history to finance_reader;

create or replace function finance.create_transaction(payload jsonb)
returns table (
    transaction_id text,
    status text,
    currency char(3),
    audit_id text,
    balance_after numeric
)
language plpgsql
as $$
declare
    txn_id text := 'txn_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16);
    audit_row_id text := 'aud_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16);
begin
    insert into finance.transactions (
        id,
        account_id,
        effective_at,
        amount,
        currency,
        direction,
        category,
        merchant,
        description,
        external_ref,
        created_by,
        updated_by
    )
    values (
        txn_id,
        payload->>'account_id',
        (payload->>'effective_at')::date,
        (payload->>'amount')::numeric(12,2),
        upper(payload->>'currency')::char(3),
        payload->>'direction',
        payload->>'category',
        nullif(payload->>'merchant', ''),
        nullif(payload->>'description', ''),
        nullif(payload->>'external_ref', ''),
        payload->>'requested_by',
        payload->>'requested_by'
    );

    insert into finance.audit_events (
        id,
        request_id,
        operation,
        entity_type,
        entity_id,
        actor,
        payload_json
    )
    values (
        audit_row_id,
        coalesce(payload->>'request_id', audit_row_id),
        'create_transaction',
        'transaction',
        txn_id,
        payload->>'requested_by',
        payload
    );

    return query
    select
        txn_id,
        'posted'::text,
        upper(payload->>'currency')::char(3),
        audit_row_id,
        null::numeric;
end;
$$;

create or replace function finance.update_transaction(target_transaction_id text, payload jsonb)
returns table (
    transaction_id text,
    status text,
    currency char(3),
    audit_id text,
    balance_after numeric
)
language plpgsql
as $$
declare
    before_row finance.transactions%rowtype;
    after_row finance.transactions%rowtype;
    audit_row_id text := 'aud_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16);
begin
    select * into before_row
    from finance.transactions
    where id = target_transaction_id;

    if not found then
        return;
    end if;

    update finance.transactions
    set
        effective_at = coalesce((payload->'changes'->>'effective_at')::date, effective_at),
        category = coalesce(payload->'changes'->>'category', category),
        merchant = coalesce(payload->'changes'->>'merchant', merchant),
        description = coalesce(payload->'changes'->>'description', description),
        external_ref = coalesce(payload->'changes'->>'external_ref', external_ref),
        updated_at = now(),
        updated_by = payload->>'requested_by'
    where id = target_transaction_id;

    select * into after_row
    from finance.transactions
    where id = target_transaction_id;

    insert into finance.transaction_revisions (
        transaction_id,
        revision_number,
        before_json,
        after_json,
        reason,
        changed_by
    )
    values (
        target_transaction_id,
        coalesce(
            (select max(revision_number) + 1 from finance.transaction_revisions where transaction_id = target_transaction_id),
            1
        ),
        to_jsonb(before_row),
        to_jsonb(after_row),
        payload->>'reason',
        payload->>'requested_by'
    );

    insert into finance.audit_events (
        id,
        request_id,
        operation,
        entity_type,
        entity_id,
        actor,
        payload_json
    )
    values (
        audit_row_id,
        coalesce(payload->>'request_id', audit_row_id),
        'update_transaction',
        'transaction',
        target_transaction_id,
        payload->>'requested_by',
        payload
    );

    return query
    select
        target_transaction_id,
        after_row.status,
        after_row.currency,
        audit_row_id,
        null::numeric;
end;
$$;

create or replace function finance.summarize_transactions(payload jsonb)
returns table (
    totals jsonb,
    lines jsonb
)
language sql
as $$
    with scoped as (
        select *
        from finance.transactions
        where account_id = payload->>'account_id'
          and effective_at >= (payload->>'date_from')::date
          and effective_at <= (payload->>'date_to')::date
          and (
            coalesce((payload->>'include_pending')::boolean, false)
            or status <> 'pending'
          )
    ),
    grouped as (
        select
            case
                when payload->>'group_by' = 'merchant' then coalesce(merchant, 'unknown')
                when payload->>'group_by' = 'day' then effective_at::text
                else category
            end as key,
            sum(case when direction = 'credit' then amount else -amount end) as amount
        from scoped
        group by 1
    )
    select
        jsonb_build_object(
            'credits', coalesce(sum(case when direction = 'credit' then amount else 0 end), 0),
            'debits', coalesce(sum(case when direction = 'debit' then amount else 0 end), 0),
            'net', coalesce(sum(case when direction = 'credit' then amount else -amount end), 0)
        ) as totals,
        coalesce(
            (
                select jsonb_agg(
                    jsonb_build_object('key', key, 'amount', amount)
                    order by key
                )
                from grouped
            ),
            '[]'::jsonb
        ) as lines
    from scoped;
$$;

grant execute on function finance.create_transaction(jsonb) to finance_writer;
grant execute on function finance.update_transaction(text, jsonb) to finance_writer;
grant execute on function finance.summarize_transactions(jsonb) to finance_reader, finance_writer;
