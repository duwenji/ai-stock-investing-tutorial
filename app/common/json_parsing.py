# LLM応答に含まれがちなMarkdownコードフェンス（```json ... ```）を取り除き、
# json.loads にそのまま渡せる文字列に正規化するユーティリティ。
import re

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        # コードフェンスで囲まれている場合は中身のみを返す。
        return match.group(1).strip()
    # コードフェンスが無ければそのまま（前後空白のみ除去して）返す。
    return stripped
