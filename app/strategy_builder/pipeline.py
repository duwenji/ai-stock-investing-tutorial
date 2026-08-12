"""AIが対話で生成したsteps（関数名とparamsの並び）をそのまま実行するエンジン。
どの関数をどの順番で呼ぶかというフロー自体はここには存在せず、stepsに
従うだけの薄い実装にする。"""

import logging

import pandas as pd

from strategy_builder.pipeline_functions import PIPELINE_FUNCTIONS

logger = logging.getLogger(__name__)


def run_pipeline(steps: list[dict], all_tickers: list[str], cache_dir) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄のticker列のみのDataFrameを初期値とし、stepsを先頭から順に適用する。
    未知のfunction名や例外を送出したステップはスキップし、トレースに理由を記録して
    処理を継続する（既存apply_filtersと同じ「壊れたLLM出力で全体を落とさない」方針）。"""
    candidates_df = pd.DataFrame({"ticker": all_tickers})
    # traceは各ステップ前後の件数推移を記録したログで、strategy_builder_tab.pyが
    # 実行結果画面にそのまま表示する（ユーザーがどのステップで絞り込まれたか追える）。
    trace = [f"開始: {len(candidates_df)}件"]

    for step in steps:
        function_name = step.get("function")
        params = step.get("params", {})
        entry = PIPELINE_FUNCTIONS.get(function_name)
        if entry is None:
            trace.append(f"{function_name}: 未知の関数のためスキップ")
            continue
        before_count = len(candidates_df)
        try:
            candidates_df = entry["run"](candidates_df, params, cache_dir)
        except Exception:
            logger.exception(
                "ステップ実行に失敗しました: function=%s params=%s", function_name, params
            )
            trace.append(f"{function_name}: エラーのためスキップ")
            continue
        trace.append(f"{function_name}: {before_count}件→{len(candidates_df)}件")

    return candidates_df, trace
