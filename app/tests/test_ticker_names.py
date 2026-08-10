from portfolio_management.ticker_names import build_candidate_names


def test_returns_universe_names_when_no_extra_holdings():
    result = build_candidate_names([], known_names={"7203.T": "トヨタ自動車"})
    assert result == {"7203.T": "トヨタ自動車"}


def test_resolves_names_for_holdings_outside_universe():
    holdings = [{"ticker": "AAA.T", "shares": 10, "cost": 100.0}]

    def fake_resolve_name(ticker):
        assert ticker == "AAA.T"
        return "フェイク株式会社"

    result = build_candidate_names(
        holdings,
        known_names={"7203.T": "トヨタ自動車"},
        resolve_name=fake_resolve_name,
    )
    assert result == {"7203.T": "トヨタ自動車", "AAA.T": "フェイク株式会社"}


def test_excludes_holdings_whose_name_cannot_be_resolved():
    holdings = [{"ticker": "BBB.T", "shares": 10, "cost": 100.0}]

    result = build_candidate_names(
        holdings,
        known_names={},
        resolve_name=lambda ticker: None,
    )
    assert result == {}


def test_universe_name_is_not_overwritten_by_holding_lookup():
    holdings = [{"ticker": "7203.T", "shares": 10, "cost": 100.0}]

    def fake_resolve_name(ticker):
        raise AssertionError("known_names内のティッカーはresolve_nameを呼ばない")

    result = build_candidate_names(
        holdings,
        known_names={"7203.T": "トヨタ自動車"},
        resolve_name=fake_resolve_name,
    )
    assert result == {"7203.T": "トヨタ自動車"}


def test_default_known_names_loaded_from_company_profiles(monkeypatch):
    import portfolio_management.ticker_names as ticker_names_module

    monkeypatch.setattr(
        ticker_names_module,
        "load_all_company_profiles",
        lambda: [{"ticker": "7203.T", "name": "トヨタ自動車"}],
    )

    result = build_candidate_names([], resolve_name=lambda ticker: None)
    assert result == {"7203.T": "トヨタ自動車"}
