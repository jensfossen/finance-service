from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, parse, request


DEFAULT_BASE_URL = os.getenv("FINANCE_SERVICE_URL", "http://127.0.0.1:8000")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finance service CLI client")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Finance service base URL",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-accounts")

    list_parser = subparsers.add_parser("list-transactions")
    list_parser.add_argument("--account-id")
    list_parser.add_argument("--date-from")
    list_parser.add_argument("--date-to")
    list_parser.add_argument("--limit", type=int, default=100)

    get_parser = subparsers.add_parser("get-transaction")
    get_parser.add_argument("transaction_id")

    create_parser = subparsers.add_parser("create-transaction")
    create_parser.add_argument("--json", required=True, help="JSON payload")

    update_parser = subparsers.add_parser("update-transaction")
    update_parser.add_argument("transaction_id")
    update_parser.add_argument("--json", required=True, help="JSON payload")

    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument("--json", required=True, help="JSON payload")

    return parser


def _http_json(method: str, url: str, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise SystemExit(f"Request failed: {exc.reason}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    base_url = args.base_url.rstrip("/")

    if args.command == "list-transactions":
        params = {
            "account_id": args.account_id,
            "date_from": args.date_from,
            "date_to": args.date_to,
            "limit": args.limit,
        }
        query = parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{base_url}/transactions"
        if query:
            url = f"{url}?{query}"
        result = _http_json("GET", url)
    elif args.command == "list-accounts":
        result = _http_json("GET", f"{base_url}/accounts")
    elif args.command == "get-transaction":
        result = _http_json("GET", f"{base_url}/transactions/{args.transaction_id}")
    elif args.command == "create-transaction":
        result = _http_json("POST", f"{base_url}/transactions", json.loads(args.json))
    elif args.command == "update-transaction":
        result = _http_json(
            "PATCH",
            f"{base_url}/transactions/{args.transaction_id}",
            json.loads(args.json),
        )
    elif args.command == "summarize":
        result = _http_json("POST", f"{base_url}/transactions/summary", json.loads(args.json))
    else:
        parser.error(f"Unknown command: {args.command}")
        return 2

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
