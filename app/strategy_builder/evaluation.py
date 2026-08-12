# AI戦略ビルダーが確定候補とした戦略JSONを、確定前に自動評価・改善する
# モジュール（Evaluator-Optimizerパターン）。
import json

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.strategy_dialogue import build_refinement_prompt


def build_evaluate_prompt(strategy: dict) -> str:
    """戦略JSONをLLMに渡し、パラメータの具体性・絞り込みすぎ・断定的な投資助言表現の
    3点をチェックさせるプロンプトを組み立てる。戻り値のJSONは{"pass", "feedback"}のみ。"""
    strategy_json = json.dumps(strategy, ensure_ascii=False, indent=2)
    return (
        "以下は投資戦略のスクリーニング/バックテストパイプライン（JSON）です。\n\n"
        f"{strategy_json}\n\n"
        '次の3つの基準で評価し、{"pass": true/false, "feedback": "..."} '
        "形式のJSONのみを出力してください（説明文やコードブロック記法は不要です）。\n"
        "1. 各ステップのfunction・paramsが具体的か（未指定・曖昧な閾値のまま"
        "残っているparamsがないか）\n"
        "2. 条件数が極端に少なく／多くなく、対象銘柄が0件になりそうな過度な"
        "絞り込みでないか\n"
        "3. 断定的な投資助言表現（例: 「必ず上がる」「今すぐ買うべき」）を"
        "含んでいないか\n\n"
        "3つすべてを満たす場合のみpassをtrueにしてください。"
        "falseの場合、feedbackに具体的な改善点を日本語で1〜2文で書いてください。"
    )


# call_llmを引数として外から差し替え可能にしておくことで、テストコードでは
# 本物のLLM呼び出しの代わりにダミー関数を渡せる（本番はdefault_call_llmが使われる）。
def evaluate_strategy(strategy: dict, call_llm=default_call_llm) -> dict:
    raw = call_llm(build_evaluate_prompt(strategy))
    try:
        result = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        result = None

    # 評価自体が失敗した場合（パース不可・pass欠落）は安全側に倒し、不合格として扱う。
    if not isinstance(result, dict) or "pass" not in result:
        return {"pass": False, "feedback": "評価結果のパースに失敗しました。"}
    return {"pass": bool(result.get("pass")), "feedback": result.get("feedback", "")}


def run_evaluation_loop(
    strategy: dict, call_llm=default_call_llm, max_iterations: int = 3
) -> dict:
    """evaluate_strategyがpass=Trueを返すかmax_iterationsに達するまで、
    build_refinement_promptによる再生成を繰り返す。

    改善案の応答がJSONとして無効、またはstepsキーを含まない場合は、
    そのイテレーションをスキップし直前のstrategyのままループを継続する。
    最後の評価イテレーションの後には改善案を生成しない。
    """
    current = strategy
    last_feedback = None
    for i in range(max_iterations):
        evaluation = evaluate_strategy(current, call_llm=call_llm)
        if evaluation["pass"]:
            return {"strategy": current, "iterations": i, "last_feedback": last_feedback}
        last_feedback = evaluation["feedback"]

        # 最後のイテレーションでは改善案を生成しない（どうせ再評価されないLLM呼び出しを省く）。
        if i < max_iterations - 1:
            raw = call_llm(build_refinement_prompt(current, last_feedback))
            try:
                refined = json.loads(strip_code_fence(raw))
            except json.JSONDecodeError:
                refined = None
            if isinstance(refined, dict) and "steps" in refined:
                current = refined

    return {"strategy": current, "iterations": max_iterations, "last_feedback": last_feedback}
