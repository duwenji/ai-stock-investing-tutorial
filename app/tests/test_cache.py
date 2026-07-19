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
