from portfolio_management.storage import load_holdings, save_holdings


def test_load_holdings_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "holdings.json"
    assert load_holdings(path) == []


def test_save_then_load_holdings_roundtrip(tmp_path):
    path = tmp_path / "holdings.json"
    holdings = [{"ticker": "7203.T", "shares": 100, "cost": 2500.0}]
    save_holdings(path, holdings)
    assert load_holdings(path) == holdings


def test_load_holdings_corrupted_file_returns_empty_list(tmp_path):
    path = tmp_path / "holdings.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_holdings(path) == []
