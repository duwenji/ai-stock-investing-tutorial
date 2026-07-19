from common.json_parsing import strip_code_fence


def test_strip_code_fence_removes_json_fence():
    text = '```json\n{"a": 1}\n```'
    assert strip_code_fence(text) == '{"a": 1}'


def test_strip_code_fence_removes_bare_fence():
    text = '```\n{"a": 1}\n```'
    assert strip_code_fence(text) == '{"a": 1}'


def test_strip_code_fence_leaves_plain_json_unchanged():
    text = '{"a": 1}'
    assert strip_code_fence(text) == '{"a": 1}'
