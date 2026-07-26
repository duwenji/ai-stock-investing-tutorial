import logging

from common.cache import read_cache, write_cache


def test_read_cache_returns_none_when_not_cached(tmp_path):
    assert read_cache(tmp_path, "some-key") is None


def test_write_then_read_cache_roundtrip(tmp_path):
    write_cache(tmp_path, "some-key", "cached content")
    assert read_cache(tmp_path, "some-key") == "cached content"


def test_different_keys_are_stored_separately(tmp_path):
    write_cache(tmp_path, "key-a", "content a")
    write_cache(tmp_path, "key-b", "content b")
    assert read_cache(tmp_path, "key-a") == "content a"
    assert read_cache(tmp_path, "key-b") == "content b"


def test_read_cache_miss_logs_info(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="common.cache"):
        read_cache(tmp_path, "missing-key")
    assert "キャッシュミス: missing-key" in caplog.text


def test_read_cache_hit_logs_info(tmp_path, caplog):
    write_cache(tmp_path, "hit-key", "content")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="common.cache"):
        read_cache(tmp_path, "hit-key")
    assert "キャッシュヒット: hit-key" in caplog.text


def test_write_cache_logs_info(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="common.cache"):
        write_cache(tmp_path, "write-key", "content")
    assert "キャッシュ書き込み: write-key" in caplog.text
