"""company_profilesに登録された全銘柄を対象に、price_history/
fundamentals_snapshots/ticker_newsを更新するバッチ。Windowsタスク
スケジューラ等から`update_market_data.bat`経由で定期実行する想定。

実行方法（ai-stock-investing-tutorial/app ディレクトリで）:
    uv run python -m scripts.update_market_data
"""

import logging
import sys

from common.concurrency import map_concurrently
from common.logging_config import log_duration, setup_logging
from data_api.stock_price_api import (
    fetch_fundamentals,
    fetch_news,
    fetch_price_history,
    load_all_company_profiles,
)
from db.engine import SessionLocal, engine, init_db

logger = logging.getLogger(__name__)


def _run_phase(phase_name: str, tickers: list[str], fetch_fn, session_factory) -> dict:
    """1データ種別（price_history/fundamentals/news）について、対象ticker全件を
    並行取得する。1銘柄の失敗が他銘柄の処理を止めないよう、失敗はtickerと
    例外内容をログした上でサマリーに記録し、処理は継続する。"""
    with log_duration(logger, f"{phase_name}更新（{len(tickers)}銘柄）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_fn(ticker, session_factory=session_factory)
        )
        failed = []
        for ticker in tickers:
            result = results[ticker]
            if isinstance(result, Exception):
                failed.append(ticker)
                logger.warning(
                    "%s取得失敗: ticker=%s error=%s", phase_name, ticker, result
                )
        success = len(tickers) - len(failed)
        logger.info(
            "%s更新完了: 成功%d件 / 失敗%d件", phase_name, success, len(failed)
        )
        return {"success": success, "failed": failed}


def run_update(session_factory=SessionLocal) -> dict:
    """company_profiles全銘柄のprice_history/fundamentals_snapshots/ticker_news
    を更新し、データ種別ごとの成功件数・失敗ticker一覧を返す。"""
    tickers = [p["ticker"] for p in load_all_company_profiles(session_factory=session_factory)]
    logger.info("市場データ更新バッチ開始: 対象%d銘柄", len(tickers))

    summary = {
        "price_history": _run_phase(
            "price_history", tickers, fetch_price_history, session_factory
        ),
        "fundamentals": _run_phase(
            "fundamentals", tickers, fetch_fundamentals, session_factory
        ),
        "news": _run_phase("news", tickers, fetch_news, session_factory),
    }
    return summary


def main() -> None:
    # app.pyと同じapp.logを共有すると、Windowsでは深夜0時のログローテーション時に
    # 双方のプロセスがファイルを開いたままだとリネームに失敗するため、バッチ専用の
    # ログファイルにする。
    setup_logging(log_filename="update_market_data.log")
    init_db(engine)
    # run_update()のデフォルト引数（session_factory=SessionLocal）はモジュール
    # import時に束縛されテスト側からのmonkeypatchが効かないため、呼び出し時に
    # SessionLocalをこの関数本体内で改めて参照する（呼び出し時のグローバル
    # 参照になりmonkeypatch.setattrで差し替え可能になる）。
    summary = run_update(session_factory=SessionLocal)
    any_failed = any(phase["failed"] for phase in summary.values())
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
