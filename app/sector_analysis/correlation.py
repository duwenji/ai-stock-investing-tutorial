import pandas as pd


def compute_sector_returns(
    prices_by_ticker: dict[str, pd.Series],
    sector_map: dict[str, str],
) -> dict[str, pd.Series]:
    """業種ごとに構成銘柄の日次リターンを等ウエイト平均した系列を返す。

    prices_by_tickerに存在しない銘柄はスキップする。構成銘柄が0件になった
    業種はキーごと結果から除外する。
    """
    returns_by_sector: dict[str, list[pd.Series]] = {}
    for ticker, sector in sector_map.items():
        prices = prices_by_ticker.get(ticker)
        if prices is None or prices.empty:
            continue
        returns_by_sector.setdefault(sector, []).append(prices.pct_change())

    sector_returns: dict[str, pd.Series] = {}
    for sector, series_list in returns_by_sector.items():
        combined = pd.concat(series_list, axis=1)
        sector_returns[sector] = combined.mean(axis=1, skipna=True)
    return sector_returns


def compute_lead_lag_pairs(
    sector_returns: dict[str, pd.Series],
    max_lag_days: int = 20,
) -> list[dict]:
    """業種の全ペア（重複なし）について、時差相関が最大となるラグを求める。

    lag > 0 で corr(sector_x, sector_y.shift(lag)) が最大になる場合、
    sector_yの過去（lag日前）の値がsector_xの現在の値と相関している
    ことになるため、sector_yが先行しsector_xが追随すると解釈する。
    共通の非欠損日数がmax_lag_days未満のペアは結果から除外する。
    """
    sectors = sorted(sector_returns.keys())
    pairs: list[dict] = []

    for i in range(len(sectors)):
        for j in range(i + 1, len(sectors)):
            sector_x, sector_y = sectors[i], sectors[j]
            x, y = sector_returns[sector_x], sector_returns[sector_y]

            best_lag = None
            best_corr = None
            for lag in range(-max_lag_days, max_lag_days + 1):
                aligned = pd.concat([x, y.shift(lag)], axis=1).dropna()
                if len(aligned) < max_lag_days:
                    continue
                corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
                if corr is None or pd.isna(corr):
                    continue
                if best_corr is None or abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag

            if best_lag is None:
                continue

            if best_lag > 0:
                leading, lagging, lag_days = sector_y, sector_x, best_lag
            elif best_lag < 0:
                leading, lagging, lag_days = sector_x, sector_y, -best_lag
            else:
                leading, lagging, lag_days = min(sector_x, sector_y), max(sector_x, sector_y), 0

            pairs.append(
                {
                    "leading_sector": leading,
                    "lagging_sector": lagging,
                    "lag_days": lag_days,
                    "correlation": float(best_corr),
                }
            )

    pairs.sort(key=lambda pair: abs(pair["correlation"]), reverse=True)
    return pairs
