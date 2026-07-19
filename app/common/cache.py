import datetime
from pathlib import Path


def get_cache_path(cache_dir: Path, key: str) -> Path:
    today = datetime.date.today().isoformat()
    return Path(cache_dir) / f"{today}-{key}.txt"


def read_cache(cache_dir: Path, key: str) -> str | None:
    path = get_cache_path(cache_dir, key)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def write_cache(cache_dir: Path, key: str, content: str) -> None:
    path = get_cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
