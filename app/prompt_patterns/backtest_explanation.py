import json

from common.disclaimer import DISCLAIMER_NOTICE


def build_backtest_prompt(ticker: str, comparison: dict[str, dict]) -> str:
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    return (
        "以下は移動平均クロスオーバー戦略のバックテスト結果です"
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
