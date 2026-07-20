"""保有銘柄群の価格系列から、ボラティリティ（変動率）や銘柄間の相関を
算出し、ポートフォリオ全体のリスク指標を提供するモジュール。"""

import pandas as pd


def assess_risk(price_histories: dict[str, pd.Series]) -> dict:
    """各銘柄の年率ボラティリティ、銘柄間の相関行列、および等金額配分を
    仮定したポートフォリオ全体のボラティリティを算出する。"""
    returns = pd.DataFrame(
        {ticker: series.pct_change().dropna() for ticker, series in price_histories.items()}
    )

    # 日次リターンの標準偏差を年間営業日数（252日）の平方根でスケールし、
    # 年率ボラティリティ（%）に変換する。
    volatility_pct = (returns.std() * (252**0.5) * 100).round(2).to_dict()
    correlation = returns.corr().round(2).to_dict()

    # ポートフォリオ全体のリスクは、各銘柄を均等配分した日次平均リターンの
    # ボラティリティとして近似する。
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
