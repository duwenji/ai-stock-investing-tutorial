import json

from strategy_builder.storage import load_strategies, save_strategy


def test_load_strategies_returns_empty_list_when_file_missing(tmp_path):
    assert load_strategies(tmp_path / "missing.json") == []


def test_load_strategies_returns_empty_list_on_malformed_json(tmp_path):
    path = tmp_path / "strategies.json"
    path.write_text("not json", encoding="utf-8")
    assert load_strategies(path) == []


def test_load_strategies_returns_empty_list_when_not_a_list(tmp_path):
    path = tmp_path / "strategies.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert load_strategies(path) == []


def test_save_strategy_appends_new_strategy(tmp_path):
    path = tmp_path / "strategies.json"
    save_strategy(path, {"strategy_name": "割安成長株", "conditions": []})
    assert load_strategies(path) == [{"strategy_name": "割安成長株", "conditions": []}]


def test_save_strategy_overwrites_existing_strategy_with_same_name(tmp_path):
    path = tmp_path / "strategies.json"
    save_strategy(path, {"strategy_name": "割安成長株", "conditions": [1]})
    save_strategy(path, {"strategy_name": "割安成長株", "conditions": [2]})
    strategies = load_strategies(path)
    assert len(strategies) == 1
    assert strategies[0]["conditions"] == [2]


def test_save_strategy_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "strategies.json"
    save_strategy(path, {"strategy_name": "A", "conditions": []})
    assert path.exists()
