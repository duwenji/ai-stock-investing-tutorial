# 自然言語の投資条件をLLMでフィルタ条件（JSON）に変換し、
# 実際の絞り込みはPython側の安全な演算子適用で行うためのモジュール。
import json
import operator

import pandas as pd

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm

# LLMが出力する演算子文字列を、実際に比較演算を行う関数へ安全にマッピングする。
# eval等を使わずホワイトリスト化することで、不正な演算子指定を無害化する。
_OPERATORS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


def build_screening_prompt(condition_text: str) -> str:
    # 自由記述の条件文をLLMに解釈させ、Python側で扱える構造化フィルタへ変換させる。
    # 使用可能なfieldを限定することで、存在しない列や不正な条件の生成を防ぐ。
    return (
        "次の投資条件をJSON形式のフィルタ配列に変換してください。\n"
        "使用できるfieldは per（PER）、pbr（PBR）、dividend_yield_pct"
        "（配当利回り、単位はパーセントの数値。例: 3%なら3）のいずれかです。\n"
        '出力形式: [{"field": "per", "operator": "<=", "value": 15}] の'
        "ようなJSON配列のみを出力してください。説明文やコードブロック記法は不要です。\n\n"
        f"条件: {condition_text}"
    )


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    # LLMが生成したフィルタ条件を順に適用する。存在しない列や未知の演算子は
    # 無視してスキップすることで、LLMの出力ゆれがあっても処理全体を落とさない。
    result = df
    for condition in filters:
        field = condition.get("field")
        op_symbol = condition.get("operator")
        value = condition.get("value")
        if field not in result.columns or op_symbol not in _OPERATORS:
            continue
        op_func = _OPERATORS[op_symbol]
        # 欠損値（NaN）は比較対象から除外してから演算子を適用する。
        mask = result[field].notna() & op_func(result[field], value)
        result = result[mask]
    return result


def build_comment_prompt(result_df: pd.DataFrame) -> str:
    # コメント生成に必要な列だけを渡し、余計な情報の混入やトークン消費を抑える。
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
        # LLM応答が不正なJSONの場合は、銘柄ごとに失敗プレースホルダーを返し処理を継続する。
        return {ticker: "コメント生成失敗" for ticker in result_df["ticker"]}
