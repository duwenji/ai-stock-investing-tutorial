"""アプリ全体のロギング設定。app/logs/配下への日次ローテーションファイル出力と、
処理の開始/完了/所要時間を一箇所で記録するためのcontextmanagerを提供する。"""

import logging
import time
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(log_dir: Path = LOG_DIR, log_filename: str = "app.log") -> None:
    """ルートロガーにファイルハンドラを設定する。

    Streamlitはユーザー操作のたびにapp.pyを再実行するため、この関数も
    そのたびに呼ばれる。同じログファイルを指す当ハンドラが既に設定済みなら
    何もせず、重複登録（＝ログの多重出力）を防ぐ。「ハンドラが1つでもあれば
    スキップ」ではなく自分自身のハンドラの有無で判定するのは、pytestの
    ログキャプチャ等、他の仕組みがルートロガーにハンドラを付けていても
    正しく初期化できるようにするため。

    log_filenameを変えることで、別プロセス（バッチスクリプト等）に専用の
    ログファイルを持たせられる。app.pyとバッチが同じapp.logを共有すると、
    Windowsでは深夜0時のログローテーション時に、もう一方のプロセスがまだ
    ファイルを開いたままだとリネームに失敗する（PermissionError）ため、
    プロセスごとにログファイルを分けることで回避する。
    """
    root_logger = logging.getLogger()
    log_path = (log_dir / log_filename).resolve()
    already_configured = any(
        isinstance(handler, TimedRotatingFileHandler)
        and Path(handler.baseFilename).resolve() == log_path
        for handler in root_logger.handlers
    )
    if already_configured:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        log_dir / log_filename,
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


@contextmanager
def log_duration(logger: logging.Logger, action: str):
    """actionの開始・完了（所要時間付き）をINFOログに、例外発生時は
    所要時間付きでERRORログ（スタックトレース込み）に記録する。
    例外は再送出し、呼び出し元の既存のエラーハンドリング（st.error等）は変えない。
    """
    logger.info("%sを開始", action)
    start = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = time.perf_counter() - start
        logger.exception("%sが失敗しました（%.2f秒）", action, elapsed)
        raise
    else:
        elapsed = time.perf_counter() - start
        logger.info("%sが完了しました（%.2f秒）", action, elapsed)
