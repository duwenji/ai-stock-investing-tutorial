"""AI戦略ビルダーが生成する戦略JSON（indicator/operatorスキーマ）を、
実際のDataFrameへの絞り込み・並び替え・判定理由生成に変換するモジュール。

既存の prompt_patterns/screening.py が使う field/記号演算子スキーマとは
別スキーマとして扱う（依頼書のシステムプロンプトが定めるJSON形式に準拠する）。
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

# indicatorの日本語表示ラベル（判定理由の文字列生成に使う）。
_INDICATOR_LABELS: dict[str, str] = {
    "PER": "PER",
    "PBR": "PBR",
    "ROE": "ROE",
    "DIVIDEND_YIELD": "配当利回り",
    "REVENUE_GROWTH": "売上高伸び率",
    "MARKET_CAP": "時価総額",
    "SECTOR": "業種",
}

# operator名 → (比較関数, 判定理由に使う日本語表現)。
_OPERATORS: dict[str, tuple] = {
    "LESS_THAN": (operator.lt, "未満"),
    "LESS_EQUAL": (operator.le, "以下"),
    "GREATER_THAN": (operator.gt, "より大"),
    "GREATER_EQUAL": (operator.ge, "以上"),
    "EQUALS": (operator.eq, "と一致"),
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
        op_entry = _OPERATORS.get(op_name)
        if column is None or column not in result.columns or op_entry is None:
            continue
        op_func, _ = op_entry
        mask = result[column].notna() & op_func(result[column], value)
        result = result[mask]
    return result


def sort_by_strategy(df: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    """戦略JSONの`sort_by`/`order`でDataFrameを並び替える。

    `sort_by`が既知のindicatorに対応する列でない場合は、並び替えを行わず
    そのまま返す。
    """
    sort_by = strategy.get("sort_by")
    column = _INDICATOR_COLUMNS.get(sort_by)
    if column is None or column not in df.columns:
        return df
    ascending = strategy.get("order") != "DESC"
    return df.sort_values(column, ascending=ascending)


def build_match_reason(row: pd.Series, conditions: list[dict]) -> str:
    """1銘柄の判定理由を、条件ごとの実際の値と閾値から機械的に組み立てる。

    LLMを呼ばず決定的に生成することで、判定理由の正確性と再現性を保証する。
    """
    parts = []
    for condition in conditions:
        indicator = condition.get("indicator")
        op_name = condition.get("operator")
        value = condition.get("value")
        column = _INDICATOR_COLUMNS.get(indicator)
        op_entry = _OPERATORS.get(op_name)
        if column is None or column not in row.index or op_entry is None:
            continue
        actual = row[column]
        if pd.isna(actual):
            continue
        _, op_label = op_entry
        label = _INDICATOR_LABELS.get(indicator, indicator)
        # SECTORのように数値でない指標（業種名など）はそのまま表示し、
        # 数値指標のみ小数第1位に丸めて表示する。
        actual_display = actual if isinstance(actual, str) else round(float(actual), 1)
        parts.append(f"{label} {actual_display}（条件: {value}{op_label}）")
    return " / ".join(parts) if parts else "条件詳細なし"
