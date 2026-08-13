"""AIが対話で生成したsteps（関数名とparamsの並び）をそのまま実行するエンジン。
どの関数をどの順番で呼ぶかというフロー自体はここには存在せず、stepsに
従うだけの薄い実装にする。"""

import logging
import time

import pandas as pd

from strategy_builder.pipeline_functions import PIPELINE_FUNCTIONS

logger = logging.getLogger(__name__)

# 03-reliability-and-cost/02-rate-limit-and-timeoutのcall_llm_with_retryサンプルと
# 揃えたリトライ設定（指数バックオフ: 1回目0秒、2回目2秒、3回目4秒）。
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 2.0


def _run_step_with_retry(run_func, candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """一時的なエラー（ネットワーク瞬断等）に対して指数バックオフでリトライする。
    未知のstrategy名等の恒久的なエラーもリトライ後は最終的に呼び出し元へ伝播する
    （リトライで解決しないため）。"""
    for attempt in range(_MAX_RETRIES):
        try:
            return run_func(candidates_df, params, cache_dir)
        except Exception:
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(_BASE_DELAY_SECONDS * (2 ** attempt))


def run_pipeline(steps: list[dict], all_tickers: list[str], cache_dir) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄のticker列のみのDataFrameを初期値とし、stepsを先頭から順に適用する。
    未知のfunction名、またはリトライしても例外を送出し続けたステップは、絞り込み漏れの
    まま後続の重いステップ（バックテスト等）が想定外に大きい候補集合に対して実行される
    のを防ぐため、候補を空にリセットしてトレースに理由を記録し、処理を継続する
    （既存apply_filtersと同じ「壊れたLLM出力で全体を落とさない」方針）。"""
    candidates_df = pd.DataFrame({"ticker": all_tickers})
    # traceは各ステップ前後の件数推移を記録したログで、strategy_builder_tab.pyが
    # 実行結果画面にそのまま表示する（ユーザーがどのステップで絞り込まれたか追える）。
    trace = [f"開始: {len(candidates_df)}件"]

    for step in steps:
        function_name = step.get("function")
        params = step.get("params", {})
        entry = PIPELINE_FUNCTIONS.get(function_name)
        if entry is None:
            trace.append(f"{function_name}: 未知の関数のため候補をリセット")
            candidates_df = candidates_df.iloc[0:0]
            continue
        before_count = len(candidates_df)
        try:
            candidates_df = _run_step_with_retry(entry["run"], candidates_df, params, cache_dir)
        except Exception:
            logger.exception(
                "ステップ実行に%d回リトライしても失敗しました: function=%s params=%s",
                _MAX_RETRIES,
                function_name,
                params,
            )
            trace.append(f"{function_name}: {_MAX_RETRIES}回リトライしても失敗のため候補をリセット")
            candidates_df = candidates_df.iloc[0:0]
            continue
        trace.append(f"{function_name}: {before_count}件→{len(candidates_df)}件")

    return candidates_df, trace
