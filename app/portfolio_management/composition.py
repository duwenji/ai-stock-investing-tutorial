def analyze_portfolio_composition(
    holdings: list[dict], current_prices: dict[str, float]
) -> dict:
    rows = []
    total_value = 0.0
    for holding in holdings:
        ticker = holding["ticker"]
        shares = holding["shares"]
        cost = holding["cost"]
        price = current_prices.get(ticker)

        value = price * shares if price is not None else None
        pnl = (price - cost) * shares if price is not None else None
        pnl_pct = (
            (price - cost) / cost * 100 if price is not None and cost else None
        )

        rows.append(
            {
                "ticker": ticker,
                "shares": shares,
                "cost": cost,
                "current_price": price,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
        if value is not None:
            total_value += value

    for row in rows:
        if row["value"] is not None and total_value:
            row["weight_pct"] = round(row["value"] / total_value * 100, 2)
        else:
            row["weight_pct"] = None

    return {"holdings": rows, "total_value": total_value}
