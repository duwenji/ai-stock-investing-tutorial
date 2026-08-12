"""ファンダメンタルズ条件（indicator/operatorスキーマ）をDataFrameへの絞り込みに
変換するモジュール。strategy_builder/pipeline_functions.py::_run_filter_by_fundamentals
（FILTER_BY_FUNDAMENTALSステップ）が内部で使う。

既存の prompt_patterns/screening.py が使う field/記号演算子スキーマとは
別スキーマとして扱う（AI戦略ビルダーのシステムプロンプトが定めるJSON形式に準拠する）。
"""

import operator

import pandas as pd

# indicator名（大文字表記）→ DataFrameの列名。
_INDICATOR_COLUMNS: dict[str, str] = {
    "PER": "per",
    "PBR": "pbr",
    "ROE": "roe_pct",
    "DIVIDEND_YIELD": "dividend_yield_pct",
    "REVENUE_GROWTH": "revenue_growth_pct",
    "MARKET_CAP": "market_cap",
    "SECTOR": "sector",
}

# operator名 → 比較関数。
_OPERATORS: dict[str, object] = {
    "LESS_THAN": operator.lt,
    "LESS_EQUAL": operator.le,
    "GREATER_THAN": operator.gt,
    "GREATER_EQUAL": operator.ge,
    "EQUALS": operator.eq,
}


def apply_strategy_conditions(df: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    """戦略JSONの`conditions`を順に適用し、絞り込んだDataFrameを返す。

    存在しないindicatorや未知のoperatorは無視してスキップすることで、
    LLM出力のゆれがあっても処理全体を落とさない（既存のapply_filtersと同方針）。
    """
    result = df
    for condition in strategy.get("conditions", []):
        indicator = condition.get("indicator")
        op_name = condition.get("operator")
        value = condition.get("value")
        column = _INDICATOR_COLUMNS.get(indicator)
        op_func = _OPERATORS.get(op_name)
        if column is None or column not in result.columns or op_func is None:
            continue
        mask = result[column].notna() & op_func(result[column], value)
        result = result[mask]
    return result
