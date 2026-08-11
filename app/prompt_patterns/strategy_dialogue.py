"""AI協調型のスクリーニングロジック構築（AI戦略ビルダー機能②）向けの
対話プロンプト構築・応答解析を行うモジュール。

data_api.llm_client.call_llm はターン単位のセッション状態を持たない
ステートレスなサブプロセス呼び出しのため、対話の各ターンで会話全履歴を
毎回プロンプトに含めて送信する。
"""

import json

from common.json_parsing import strip_code_fence
from strategy_builder.pipeline_functions import PIPELINE_FUNCTIONS


def _format_pipeline_functions_for_prompt() -> str:
    lines = []
    for name, entry in PIPELINE_FUNCTIONS.items():
        params_lines = "\n".join(
            f"    - {param}: {description}"
            for param, description in entry["params_schema"].items()
        )
        lines.append(f"- {name}: {entry['description']}\n  params:\n{params_lines}")
    return "\n".join(lines)


_PERSONA_INSTRUCTIONS_TEMPLATE = """\
あなた（AI）は、ユーザーの投資アイデアを厳密な「株式スクリーニング・パイプライン」へと
昇華させるプロのクオンツ・アナリストです。以下のステップに従ってユーザーをナビゲートしてください。

【ステップ1: アイデアの定量化】
ユーザーから「考え方」が入力されたら、それを歓迎し、以下の要素を具体化するための質問や提案を
1〜2個、短く行ってください。
1. どの関数（複数可）をどの順番で使うか
2. 各関数のパラメータ（戦略名・期間・閾値等）
このステップでは、説明文以外は出力しないでください。JSON形式は使わないでください。

【使用できる関数一覧】
{functions}

【ステップ2: 構造化データの出力】
ユーザーと条件が合意できたら、それ以外の説明文を一切含めず、必ず次のJSON形式のみを
```json コードブロックで返してください。
```json
{{
  "strategy_name": "確定した戦略名",
  "steps": [
    {{"function": "関数名", "params": {{...}}}}
  ]
}}
```
stepsは上記の関数一覧にある関数名のみを使い、必要な順番・組み合わせで並べてください。
"""


def build_dialogue_prompt(history: list[dict], sectors: list[str] | None = None) -> str:
    """会話履歴（[{"role": "user"|"assistant", "content": str}, ...]）から、
    ペルソナ指示と会話全文を含む1回分のLLM呼び出し用プロンプトを組み立てる。

    sectorsを渡すと、SECTOR条件のvalueに使うべき正確な業種名の一覧を
    プロンプトに追加する（表記ゆれのない条件生成のため）。
    """
    sector_block = ""
    if sectors:
        sector_list = "、".join(sectors)
        sector_block = (
            "\n\nFILTER_BY_FUNDAMENTALSでSECTOR条件を使う場合、valueは次の業種名のいずれか"
            f"一つをそのまま正確に使ってください（表記ゆれを吸収し、最も近いものを選ぶこと）: {sector_list}"
        )
    persona = _PERSONA_INSTRUCTIONS_TEMPLATE.format(
        functions=_format_pipeline_functions_for_prompt()
    )
    transcript_lines = [
        f"{'ユーザー' if turn['role'] == 'user' else 'AI'}: {turn['content']}"
        for turn in history
    ]
    transcript = "\n".join(transcript_lines)
    return (
        f"{persona}{sector_block}"
        f"\n\n【これまでの会話】\n{transcript}\n\n【あなたの次の発言】"
    )


def parse_dialogue_response(raw: str) -> dict:
    """LLM応答を判定する。

    JSONコードブロックとして解析でき、かつ`strategy_name`と（`steps`または
    `conditions`）を含む場合は `{"kind": "strategy", "strategy": {...}}` を返す
    （`steps`は新形式、`conditions`は後方互換の旧形式）。それ以外は質問・提案
    テキストとして `{"kind": "question", "text": raw}` を返す。
    """
    try:
        parsed = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {"kind": "question", "text": raw.strip()}

    if isinstance(parsed, dict) and "strategy_name" in parsed:
        if "steps" in parsed or "conditions" in parsed:
            return {"kind": "strategy", "strategy": parsed}
    return {"kind": "question", "text": raw.strip()}


def build_refinement_prompt(pending_strategy: dict, feedback: str) -> str:
    """確定候補の戦略JSONと評価フィードバックから、修正版JSONを1回で
    生成させる軽量プロンプト（Evaluator-Optimizerパターンの改善ステップ）。
    既存の対話ペルソナ指示（_PERSONA_INSTRUCTIONS_TEMPLATE）は使わない。"""
    strategy_json = json.dumps(pending_strategy, ensure_ascii=False, indent=2)
    return (
        "以下は投資戦略のスクリーニングパイプライン（JSON）と、その評価フィードバックです。\n\n"
        f"【現在の条件】\n{strategy_json}\n\n"
        f"【評価フィードバック】\n{feedback}\n\n"
        "このフィードバックを踏まえて修正し、それ以外の説明文を一切含めず、"
        "必ず次のJSON形式のみを```json コードブロックで返してください。\n"
        "```json\n"
        "{\n"
        '  "strategy_name": "修正後の戦略名",\n'
        '  "steps": [\n'
        '    {"function": "関数名", "params": {}}\n'
        "  ]\n"
        "}\n"
        "```\n"
        f"{_format_pipeline_functions_for_prompt()}"
    )
