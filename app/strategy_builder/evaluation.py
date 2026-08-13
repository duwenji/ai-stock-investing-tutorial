# AI戦略ビルダーが確定候補とした戦略JSONを、確定前に自動評価・改善する
# モジュール（Evaluator-Optimizerパターン）。
import json
import uuid

from common.ai_generation_log import log_ai_generation
from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm
from db.engine import SessionLocal
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
# session_id未指定時はこの呼び出し単体のための使い捨てセッションを自動発行する。
# run_evaluation_loopから呼ばれる場合は、対話全体で共有する既存のsession_idが渡される。
def evaluate_strategy(
    strategy: dict,
    call_llm=default_call_llm,
    *,
    session_id: str | None = None,
    turn_index: int = 0,
    user_id: int | None = None,
    session_factory=SessionLocal,
) -> dict:
    prompt = build_evaluate_prompt(strategy)
    raw = call_llm(prompt)
    try:
        parsed_json = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        parsed_json = None

    # 評価自体が失敗した場合（パース不可・pass欠落）は安全側に倒し、不合格として扱う。
    if not isinstance(parsed_json, dict) or "pass" not in parsed_json:
        result = {"pass": False, "feedback": "評価結果のパースに失敗しました。"}
    else:
        result = {
            "pass": bool(parsed_json.get("pass")),
            "feedback": parsed_json.get("feedback", ""),
        }

    log_ai_generation(
        session_id or uuid.uuid4().hex,
        "strategy_evaluate",
        facts={"strategy": strategy},
        prompt=prompt,
        ai_output=raw,
        turn_index=turn_index,
        user_id=user_id,
        session_factory=session_factory,
    )
    return result


def run_evaluation_loop(
    strategy: dict,
    call_llm=default_call_llm,
    max_iterations: int = 3,
    *,
    session_id: str | None = None,
    turn_index_start: int = 0,
    user_id: int | None = None,
    session_factory=SessionLocal,
) -> dict:
    """evaluate_strategyがpass=Trueを返すかmax_iterationsに達するまで、
    build_refinement_promptによる再生成を繰り返す。

    改善案の応答がJSONとして無効、またはstepsキーを含まない場合は、
    そのイテレーションをスキップし直前のstrategyのままループを継続する。
    最後の評価イテレーションの後には改善案を生成しない。

    session_id未指定時はこのループ全体のための使い捨てセッションを自動発行し、
    評価・改善の全呼び出しをそのセッション内の連番turn_indexで記録する。
    戻り値のnext_turn_indexは、呼び出し元（対話ターン）が続けて同じセッションに
    ログを積み増す際に使うturn_indexの開始値。
    """
    resolved_session_id = session_id or uuid.uuid4().hex
    current = strategy
    last_feedback = None
    turn = turn_index_start
    for i in range(max_iterations):
        evaluation = evaluate_strategy(
            current,
            call_llm=call_llm,
            session_id=resolved_session_id,
            turn_index=turn,
            user_id=user_id,
            session_factory=session_factory,
        )
        turn += 1
        if evaluation["pass"]:
            return {
                "strategy": current,
                "iterations": i,
                "last_feedback": last_feedback,
                "next_turn_index": turn,
            }
        last_feedback = evaluation["feedback"]

        # 最後のイテレーションでは改善案を生成しない（どうせ再評価されないLLM呼び出しを省く）。
        if i < max_iterations - 1:
            refine_prompt = build_refinement_prompt(current, last_feedback)
            raw = call_llm(refine_prompt)
            log_ai_generation(
                resolved_session_id,
                "strategy_refine",
                facts={"strategy": current, "feedback": last_feedback},
                prompt=refine_prompt,
                ai_output=raw,
                turn_index=turn,
                user_id=user_id,
                session_factory=session_factory,
            )
            turn += 1
            try:
                refined = json.loads(strip_code_fence(raw))
            except json.JSONDecodeError:
                refined = None
            if isinstance(refined, dict) and "steps" in refined:
                current = refined

    return {
        "strategy": current,
        "iterations": max_iterations,
        "last_feedback": last_feedback,
        "next_turn_index": turn,
    }
