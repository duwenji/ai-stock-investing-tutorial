import pandas as pd


def assess_risk(price_histories: dict[str, pd.Series]) -> dict:
    returns = pd.DataFrame(
        {ticker: series.pct_change().dropna() for ticker, series in price_histories.items()}
    )

    volatility_pct = (returns.std() * (252**0.5) * 100).round(2).to_dict()
    correlation = returns.corr().round(2).to_dict()

    portfolio_volatility_pct = None
    if len(returns.columns) > 0:
        portfolio_volatility_pct = round(
            returns.mean(axis=1).std() * (252**0.5) * 100, 2
        )

    return {
        "volatility_pct": volatility_pct,
        "correlation": correlation,
        "portfolio_volatility_pct": portfolio_volatility_pct,
    }
