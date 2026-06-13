from finance_service.client import main


def test_cli_list_transactions_help_parses() -> None:
    try:
        main(["list-transactions", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
