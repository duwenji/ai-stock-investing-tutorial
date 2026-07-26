# LLM呼び出し結果などをファイルベースで日次キャッシュするためのユーティリティ。
# 同じ日であれば再利用し、無駄なAPI呼び出し（コスト・レイテンシ）を避ける。
import datetime
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_cache_path(cache_dir: Path, key: str) -> Path:
    # キャッシュを日付単位で分けることで、日をまたいだ古い情報を自然に無効化する。
    today = datetime.date.today().isoformat()
    return Path(cache_dir) / f"{today}-{key}.txt"


def read_cache(cache_dir: Path, key: str) -> str | None:
    path = get_cache_path(cache_dir, key)
    if path.exists():
        logger.info("キャッシュヒット: %s", key)
        return path.read_text(encoding="utf-8")
    logger.info("キャッシュミス: %s", key)
    return None


def write_cache(cache_dir: Path, key: str, content: str) -> None:
    path = get_cache_path(cache_dir, key)
    # キャッシュディレクトリが未作成の場合に備え、書き込み前に作成しておく。
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("キャッシュ書き込み: %s", key)
