# 選択した2業種・1周期帯のウェーブレット分析スナップショット（直近の支配的ラグ・
# コヒーレンス）をLLMに解説させるプロンプトを組み立てるモジュール。
# ウェーブレット計算自体はPython側（sector_analysis/wavelet.py）で完了させる。
from data_api.llm_client import call_llm as default_call_llm


def build_wavelet_prompt(
    sector_x: str, sector_y: str, band: str, snapshot: dict
) -> str:
    # 事前に算出済みの直近スナップショットをそのまま渡し、LLMには解釈のみ任せる。
    date_str = snapshot["date"].strftime("%Y-%m-%d")
    lag = snapshot["dominant_lag_days"]
    coherence = snapshot["avg_coherence"]
    leading = sector_x if lag >= 0 else sector_y
    lagging = sector_y if lag >= 0 else sector_x
    return (
        f"以下は業種「{sector_x}」と業種「{sector_y}」について、周期帯「{band}」における"
        "ウェーブレット分析（クロスウェーブレット・コヒーレンスと位相差）の直近時点の"
        "計算結果です（Python側で計算済みのため再計算は不要です）。\n\n"
        f"- 日付: {date_str}\n"
        f"- 支配的ラグ: 約{abs(lag):.1f}営業日（{leading}が{lagging}に先行）\n"
        f"- コヒーレンス（関係の確からしさ、0〜1）: {coherence:.2f}\n\n"
        "この結果について、投資家向けの解説コメントを日本語で3〜4文程度で作成してください。\n"
        "以下を必ず含めてください。\n"
        "1. 上記の先行・追随関係とコヒーレンスの水準（高い/中程度/低い）が何を意味するかの説明\n"
        "2. これはあくまで過去の統計的傾向であり、将来の値動きを保証するものではないこと\n\n"
        # 統計的傾向の紹介にとどめ、売買を促す表現を避けさせる。
        "出力は事実の説明と教育的な考察にとどめ、「買うべき」「今すぐこの業種を"
        "売買すべき」のような指示的な表現は使わないでください。\n"
        "出力形式: コメント本文のみをプレーンテキストで出力してください。"
        "コードブロックや前置きは不要です。"
    )


def generate_wavelet_explanation(
    sector_x: str,
    sector_y: str,
    band: str,
    snapshot: dict,
    call_llm=default_call_llm,
) -> str:
    prompt = build_wavelet_prompt(sector_x, sector_y, band, snapshot)
    return call_llm(prompt).strip()
