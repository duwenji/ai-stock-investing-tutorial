import logging
from logging.handlers import TimedRotatingFileHandler

import pytest

from common.logging_config import log_duration, setup_logging


@pytest.fixture(autouse=True)
def _clean_root_logger():
    # setup_loggingはStreamlitの再実行のたびに呼ばれる想定のため、テスト間で
    # ルートロガーの状態（ハンドラ・レベル）が汚染されないようリセットする。
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    for handler in original_handlers:
        root_logger.removeHandler(handler)
    yield
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)


def test_setup_logging_creates_log_file_with_message(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)

    logging.getLogger("test_setup_logging_creates_log_file_with_message").info("hello")
    for handler in logging.getLogger().handlers:
        handler.flush()

    log_file = log_dir / "app.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)
    setup_logging(log_dir=log_dir)

    # pytest自身がルートロガーにログキャプチャ用ハンドラを付けているため、
    # 「ハンドラ総数」ではなく自分が追加したTimedRotatingFileHandlerの数で判定する。
    matching = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert len(matching) == 1


def test_log_duration_logs_start_and_completion(caplog):
    logger = logging.getLogger("test_log_duration_success")
    with caplog.at_level(logging.INFO, logger="test_log_duration_success"):
        with log_duration(logger, "テスト処理"):
            pass

    assert "テスト処理を開始" in caplog.text
    assert "テスト処理が完了しました" in caplog.text


def test_log_duration_logs_failure_and_reraises(caplog):
    logger = logging.getLogger("test_log_duration_failure")
    with caplog.at_level(logging.INFO, logger="test_log_duration_failure"):
        with pytest.raises(ValueError):
            with log_duration(logger, "失敗処理"):
                raise ValueError("boom")

    assert "失敗処理を開始" in caplog.text
    assert "失敗処理が失敗しました" in caplog.text
