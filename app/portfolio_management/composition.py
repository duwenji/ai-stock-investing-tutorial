"""保有銘柄一覧と現在値から、評価額・損益・ポートフォリオ内構成比を
算出するモジュール。portfolio_tab.py・qa_tab.py・review.py（AIレビュー生成）
から共通の集計ロジックとして呼ばれる。"""


def analyze_portfolio_composition(
    holdings: list[dict], current_prices: dict[str, float]
) -> dict:
    """各保有銘柄の評価額・損益（金額/率）を計算し、ポートフォリオ全体に
    占める構成比（weight_pct）を付与する。現在値が取得できない銘柄は
    評価額等をNoneとして扱い、集計から除外する。"""
    rows = []
    total_value = 0.0
    for holding in holdings:
        ticker = holding["ticker"]
        shares = holding["shares"]
        cost = holding["cost"]
        price = current_prices.get(ticker)

        # 現在値が取得できない銘柄は評価額・損益を算出不能（None）とする。
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

    # 全銘柄の評価額合計が確定した後に、各銘柄の構成比（%）を計算する。
    for row in rows:
        if row["value"] is not None and total_value:
            row["weight_pct"] = round(row["value"] / total_value * 100, 2)
        else:
            row["weight_pct"] = None

    return {"holdings": rows, "total_value": total_value}
