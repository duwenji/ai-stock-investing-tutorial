import json

from common.disclaimer import DISCLAIMER_NOTICE
from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm


def build_backtest_prompt(
    ticker: str, comparison: dict[str, dict], strategy_name: str = "移動平均クロスオーバー"
) -> str:
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    return (
        f"以下は{strategy_name}戦略のバックテスト結果です"
        "（Python側でパラメータ組ごとに計算済みのため再計算は不要です）。\n\n"
        f"【対象銘柄】{ticker}\n"
        f"【パラメータ組ごとの結果（JSON）】\n{comparison_json}\n\n"
        "この結果を投資初心者にも分かる言葉で説明してください。\n"
        "以下を必ず含めてください。\n"
        "1. 各パラメータ組について、戦略のリターンとベンチマーク（Buy&Hold）の比較\n"
        "2. 勝率・最大ドローダウンの意味\n"
        "3. 過去の結果が将来の成績を保証しないこと、"
        "および過学習・取引コストやスリッページを考慮しきれていない可能性への注意喚起\n"
        "4. パラメータ組同士の結果を比較し、大きく異なっている場合は"
        "パラメータ選択に対する過学習リスクを強調すること\n"
        "5. 追加で確認する価値がある指標やシナリオの提案（実行はしない）\n\n"
        "出力は事実の説明と教育的な提案にとどめ、「買うべき」「このルールで"
        "今すぐ売買すべき」のような指示的な表現は使わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )


def build_ranking_comment_prompt(ranking_rows: list[dict]) -> str:
    rows = [
        {
            "ticker": row["ticker"],
            "total_return_pct": row["total_return_pct"],
            "risk_adjusted_return": row["risk_adjusted_return"],
        }
        for row in ranking_rows
    ]
    rows_json = json.dumps(rows, ensure_ascii=False)
    return (
        "以下は複数銘柄のバックテスト結果ランキング（リスク調整済みリターン降順）です。"
        "銘柄ごとに投資家向けの一言コメントを日本語で1文ずつ作成してください。"
        "断定的な売買判断は含めないでください。\n"
        '出力形式: {"<ticker>": "<コメント>"} というJSONのみを出力してください。\n\n'
        f"{rows_json}"
    )


def generate_ranking_comments(
    ranking_rows: list[dict], call_llm=default_call_llm
) -> dict[str, str]:
    if not ranking_rows:
        return {}

    prompt = build_ranking_comment_prompt(ranking_rows)
    raw = call_llm(prompt)
    try:
        return json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {row["ticker"]: "コメント生成失敗" for row in ranking_rows}
