# セクターローテーション（業種間の先行・追随関係）の分析結果をLLMに解説させる
# プロンプトを組み立てるモジュール。相関計算自体はPython側で完了させる。
import json

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm


def build_sector_rotation_prompt(top_pairs: list[dict]) -> str:
    # 事前に算出済みのリード・ラグ相関ペアをそのままJSONで渡し、LLMには解釈のみ任せる。
    # LLMには整形不要のためindentは付けず、トークン消費を抑える。
    pairs_json = json.dumps(top_pairs, ensure_ascii=False)
    return (
        "以下は業種（セクター）間の値動きの時差相関（リード・ラグ）を、"
        "過去の株価データから計算した結果です"
        "（Python側で計算済みのため再計算は不要です）。\n\n"
        f"【相関上位ペア（JSON）】\n{pairs_json}\n\n"
        "各ペアについて、投資家向けの解説コメントを日本語で1文ずつ作成してください。\n"
        "以下を必ず含めてください。\n"
        "1. leading_sector（先行業種）の値動きに、lagging_sector（追随業種）が"
        "lag_days営業日遅れて追随する傾向がある、という過去データ上の傾向の説明\n"
        "2. これはあくまで過去の統計的傾向であり、将来の値動きを保証するものではないこと\n\n"
        # 統計的傾向の紹介にとどめ、売買を促す表現を避けさせる。
        "出力は事実の説明と教育的な考察にとどめ、「買うべき」「今すぐこの業種を"
        "売買すべき」のような指示的な表現は使わないでください。\n"
        '出力形式: {"<leading_sector>-><lagging_sector>": "<コメント>"} という'
        "JSONのみを出力してください。コードブロックは不要です。"
    )


def generate_sector_rotation_comments(
    top_pairs: list[dict],
    call_llm=default_call_llm,
) -> dict[str, str]:
    if not top_pairs:
        return {}

    prompt = build_sector_rotation_prompt(top_pairs)
    raw = call_llm(prompt)
    try:
        return json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        # LLM応答のJSONパースに失敗しても処理を継続できるよう、
        # ペアごとに失敗を示すプレースホルダーコメントで代替する。
        return {
            f"{pair['leading_sector']}->{pair['lagging_sector']}": "コメント生成失敗"
            for pair in top_pairs
        }
