from data_api.stock_price_api import fetch_japanese_name as default_resolve_name
from screening.universe import UNIVERSE_NAMES


def build_candidate_names(
    holdings: list[dict],
    universe_names: dict[str, str] = UNIVERSE_NAMES,
    resolve_name=default_resolve_name,
) -> dict[str, str]:
    candidates = dict(universe_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = resolve_name(ticker)
        if name:
            candidates[ticker] = name
    return candidates
