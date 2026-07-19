from data_api.stock_price_api import fetch_fundamentals as default_fetch_fundamentals
from screening.universe import UNIVERSE_NAMES


def build_candidate_names(
    holdings: list[dict],
    universe_names: dict[str, str] = UNIVERSE_NAMES,
    fetch_fundamentals=default_fetch_fundamentals,
) -> dict[str, str]:
    candidates = dict(universe_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = fetch_fundamentals(ticker).get("name")
        if name:
            candidates[ticker] = name
    return candidates
