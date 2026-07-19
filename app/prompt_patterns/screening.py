import json
import operator

import pandas as pd

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm

_OPERATORS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


def build_screening_prompt(condition_text: str) -> str:
    return (
        "次の投資条件をJSON形式のフィルタ配列に変換してください。\n"
        "使用できるfieldは per（PER）、pbr（PBR）、dividend_yield_pct"
        "（配当利回り、単位はパーセントの数値。例: 3%なら3）のいずれかです。\n"
        '出力形式: [{"field": "per", "operator": "<=", "value": 15}] の'
        "ようなJSON配列のみを出力してください。説明文やコードブロック記法は不要です。\n\n"
        f"条件: {condition_text}"
    )


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    result = df
    for condition in filters:
        field = condition.get("field")
        op_symbol = condition.get("operator")
        value = condition.get("value")
        if field not in result.columns or op_symbol not in _OPERATORS:
            continue
        op_func = _OPERATORS[op_symbol]
        mask = result[field].notna() & op_func(result[field], value)
        result = result[mask]
    return result


def build_comment_prompt(result_df: pd.DataFrame) -> str:
    rows = result_df[["ticker", "per", "dividend_yield_pct"]].to_dict(orient="records")
    rows_json = json.dumps(rows, ensure_ascii=False)
    return (
        "以下の銘柄データを見て、銘柄ごとに投資家向けの一言コメントを"
        "日本語で1文ずつ作成してください。断定的な売買判断は含めないでください。\n"
        '出力形式: {"<ticker>": "<コメント>"} というJSONのみを出力してください。\n\n'
        f"{rows_json}"
    )


def generate_screening_comments(
    result_df: pd.DataFrame, call_llm=default_call_llm
) -> dict[str, str]:
    if result_df.empty:
        return {}

    prompt = build_comment_prompt(result_df)
    raw = call_llm(prompt)
    try:
        return json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {ticker: "コメント生成失敗" for ticker in result_df["ticker"]}
