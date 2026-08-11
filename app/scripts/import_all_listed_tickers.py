"""JPXの東証上場銘柄一覧（data_j.xls）を毎回最新版でダウンロードし、
company_profilesへ全銘柄（ETF/REIT/PRO Market等を含む）を投入するバッチ。
既存tickerの既存値（yfinance取得済みの値や管理者編集値）は上書きしない。

data_j.xlsはJPXが月末ごとに同一URL配下で更新版へ差し替えている（＝アプリに
固定コミットされたapp/docs/data_j.xlsは経時的に古くなる）ため、このスクリプトは
実行のたびにJPX公式サイトから最新のリンクを解決してダウンロードし、あわせて
app/docs/data_j.xlsをダウンロード内容で上書きして参照ファイルを最新に保つ。

実行方法（ai-stock-investing-tutorial/app ディレクトリで）:
    uv run python -m scripts.import_all_listed_tickers
"""

import logging
import re
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from common.logging_config import log_duration, setup_logging
from db.engine import SessionLocal, engine, init_db, upsert_company_profile_name_and_sector_jp

logger = logging.getLogger(__name__)

_LISTING_PAGE_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
_LISTING_LINK_RE = re.compile(r'href="([^"]*data_j\.xls)"')
_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}
LISTING_ARCHIVE_PATH = Path(__file__).resolve().parent.parent / "docs" / "data_j.xls"


def resolve_latest_listing_url(listing_page_url: str = _LISTING_PAGE_URL) -> str:
    """JPXのランディングページから、最新の東証上場銘柄一覧(data_j.xls)への
    リンクを解決する。JPXは月末更新のたびにファイルを同一URL配下で差し替える
    運用のため、URLを固定でハードコードせず毎回このページから解決する。"""
    response = requests.get(listing_page_url, headers=_REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    match = _LISTING_LINK_RE.search(response.text)
    if match is None:
        raise ValueError(f"data_j.xlsへのリンクが見つかりません: {listing_page_url}")
    href = match.group(1)
    if href.startswith("http"):
        return href
    return f"https://www.jpx.co.jp{href}"


def download_listing_xls_bytes(archive_path: Path = LISTING_ARCHIVE_PATH) -> bytes:
    """最新のdata_j.xlsをダウンロードし、生のバイト列を返す。あわせて
    archive_path（既定はapp/docs/data_j.xls）へダウンロード内容をそのまま
    上書き保存し、リポジトリに固定コミットされた参照ファイルを最新に保つ。"""
    url = resolve_latest_listing_url()
    logger.info("東証上場銘柄一覧ダウンロード開始: url=%s", url)
    response = requests.get(url, headers=_REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    logger.info("東証上場銘柄一覧ダウンロード完了: %dバイト", len(response.content))

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(response.content)
    logger.info("東証上場銘柄一覧を保存: path=%s", archive_path)

    return response.content


def normalize_listing_rows(df: pd.DataFrame) -> list[dict]:
    """data_j.xlsのDataFrame（コード/銘柄名/17業種区分列を持つ）を、
    company_profiles投入用の{"ticker", "name", "sector_jp"}のリストに変換する。
    17業種区分が未分類を示す"-"（ETF・REIT・PRO Market・種類株式等）はNoneにする。"""
    rows = []
    for _, row in df.iterrows():
        sector_jp = row["17業種区分"]
        if sector_jp == "-" or pd.isna(sector_jp):
            sector_jp = None
        rows.append(
            {
                "ticker": f"{row['コード']}.T",
                "name": row["銘柄名"],
                "sector_jp": sector_jp,
            }
        )
    return rows


def run_import(session_factory=SessionLocal, df: pd.DataFrame | None = None) -> dict:
    """JPX上場銘柄一覧をcompany_profilesへupsertする。dfを渡すとダウンロードを
    スキップする（テスト用）。既存tickerのname/sector_jpは、現在NULLの場合のみ
    埋める（yfinance取得済みの値・管理者編集値は上書きしない）。"""
    if df is None:
        df = pd.read_excel(BytesIO(download_listing_xls_bytes()))

    rows = normalize_listing_rows(df)
    with log_duration(logger, f"company_profiles全銘柄投入（{len(rows)}銘柄）"):
        with session_factory() as session:
            connection = session.connection()
            for row in rows:
                upsert_company_profile_name_and_sector_jp(
                    connection, row["ticker"], row["name"], row["sector_jp"]
                )
            session.commit()
        logger.info("company_profiles全銘柄投入完了: %d銘柄", len(rows))
    return {"total": len(rows)}


def main() -> None:
    setup_logging(log_filename="import_all_listed_tickers.log")
    init_db(engine)
    summary = run_import(session_factory=SessionLocal)
    logger.info("東証上場銘柄インポートバッチ完了: %s", summary)
    sys.exit(0)


if __name__ == "__main__":
    main()
