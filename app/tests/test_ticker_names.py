from portfolio_management.ticker_names import build_candidate_names


def test_returns_universe_names_when_no_extra_holdings():
    result = build_candidate_names([], universe_names={"7203.T": "トヨタ自動車"})
    assert result == {"7203.T": "トヨタ自動車"}


def test_resolves_names_for_holdings_outside_universe():
    holdings = [{"ticker": "AAA.T", "shares": 10, "cost": 100.0}]

    def fake_fetch_fundamentals(ticker):
        assert ticker == "AAA.T"
        return {"name": "Fake Corp"}

    result = build_candidate_names(
        holdings,
        universe_names={"7203.T": "トヨタ自動車"},
        fetch_fundamentals=fake_fetch_fundamentals,
    )
    assert result == {"7203.T": "トヨタ自動車", "AAA.T": "Fake Corp"}


def test_excludes_holdings_whose_name_cannot_be_resolved():
    holdings = [{"ticker": "BBB.T", "shares": 10, "cost": 100.0}]

    result = build_candidate_names(
        holdings,
        universe_names={},
        fetch_fundamentals=lambda ticker: {"name": None},
    )
    assert result == {}


def test_universe_name_is_not_overwritten_by_holding_lookup():
    holdings = [{"ticker": "7203.T", "shares": 10, "cost": 100.0}]

    def fake_fetch_fundamentals(ticker):
        raise AssertionError("universe内のティッカーはfetch_fundamentalsを呼ばない")

    result = build_candidate_names(
        holdings,
        universe_names={"7203.T": "トヨタ自動車"},
        fetch_fundamentals=fake_fetch_fundamentals,
    )
    assert result == {"7203.T": "トヨタ自動車"}
