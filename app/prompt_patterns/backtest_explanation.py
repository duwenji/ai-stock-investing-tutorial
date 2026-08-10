# バックテスト結果をLLMに解説させるためのプロンプトを組み立てるモジュール。
# 数値計算はすべてPython側で完了させ、LLMには「結果の解釈・説明」のみを担わせる。
import json

from common.disclaimer import DISCLAIMER_NOTICE
from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm


def build_backtest_prompt(
    ticker: str,
    comparison: dict[str, dict],
    stability: dict,
    strategy_name: str = "移動平均クロスオーバー",
) -> str:
    # 再計算を防ぐため、Python側で算出済みのバックテスト結果をJSONとしてそのまま埋め込む。
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    stability_json = json.dumps(stability, ensure_ascii=False, indent=2, default=str)
    return (
        f"以下は{strategy_name}戦略のバックテスト結果です"
        "（Python側でパラメータの近傍グリッドサーチまで計算済みのため再計算は不要です）。\n\n"
        f"【対象銘柄】{ticker}\n"
        f"【近傍グリッド内の最良/最悪パラメータの結果（JSON）】\n{comparison_json}\n\n"
        f"【近傍グリッド全体の安定性（JSON、Python側で算出済み）】\n{stability_json}\n\n"
        "この結果を投資初心者にも分かる言葉で説明してください。\n"
        "以下を必ず含めてください。\n"
        "1. 最良パラメータの戦略リターンとベンチマーク（Buy&Hold）の比較\n"
        "2. 勝率・最大ドローダウンの意味\n"
        "3. 過去の結果が将来の成績を保証しないこと、"
        "および過学習・取引コストやスリッページを考慮しきれていない可能性への注意喚起\n"
        "4. 近傍グリッド全体の安定性（is_stableとcvの値）を踏まえ、"
        "is_stableがfalseの場合は特にパラメータ選択に対する過学習リスクを強調すること\n"
        "5. 追加で確認する価値がある指標やシナリオの提案（実行はしない）\n\n"
        # 投資助言と誤解されないよう、指示的な表現を明示的に禁止する。
        "出力は事実の説明と教育的な提案にとどめ、「買うべき」「このルールで"
        "今すぐ売買すべき」のような指示的な表現は使わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )


def build_improvement_prompt(
    ticker: str,
    comparison: dict[str, dict],
    explanation: str,
    stability: dict,
    strategy_name: str = "移動平均クロスオーバー",
) -> str:
    # Step1（結果解説）の出力を入力として受け取り、追加で検討すべき観点を
    # 生成させる2段階目のプロンプト（Prompt Chaining）。
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    stability_json = json.dumps(stability, ensure_ascii=False, indent=2, default=str)
    return (
        f"以下は{strategy_name}戦略のバックテスト結果（Python側で計算済み）と、"
        "その結果について別のAIが作成した解説文です。\n\n"
        f"【対象銘柄】{ticker}\n"
        f"【近傍グリッド内の最良/最悪パラメータの結果（JSON）】\n{comparison_json}\n\n"
        f"【近傍グリッド全体の安定性（JSON、Python側で算出済み）】\n{stability_json}\n\n"
        f"【既存の解説】\n{explanation}\n\n"
        "この解説を踏まえ、投資家が追加で検討する価値がある観点を"
        "日本語で2〜3個、簡潔に提案してください。\n"
        "以下を必ず考慮してください。\n"
        "1. is_stableがfalseの場合、過学習を避けるために確認すべき追加のデータ期間やパラメータ幅\n"
        "2. 取引コストやスリッページなど、本バックテストが考慮していない要因\n\n"
        "出力は教育的な提案にとどめ、「買うべき」「このルールで今すぐ売買すべき」"
        "のような指示的な表現は使わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )


def build_ranking_comment_prompt(ranking_rows: list[dict]) -> str:
    # LLMに渡す情報を必要最小限（ティッカー・リターン・リスク調整後リターン）に絞り、
    # 余計な情報でコメントの精度が落ちたりトークンを浪費したりしないようにする。
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
        # 後続処理でパースしやすいよう、JSON形式のみを厳密に指定する。
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
        # LLMの応答が壊れたJSONだった場合でも処理を止めず、
        # 銘柄ごとに失敗を示すプレースホルダーで代替する。
        return {row["ticker"]: "コメント生成失敗" for row in ranking_rows}
