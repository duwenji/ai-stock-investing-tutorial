"""yfinanceおよびYahoo!ファイナンス（日本版）から株価・ファンダメンタルズ・
ニュース等の市場データを取得するAPIラッパー群。取得結果のキャッシュ・
複数銘柄の並行取得もあわせて提供する。"""

import datetime
import logging
import re

import pandas as pd
import requests
import yfinance as yf

from common.concurrency import map_concurrently
from common.logging_config import log_duration
from db.engine import SessionLocal
from db.models import CompanyProfile, FundamentalsSnapshot, PriceHistory, TickerNews

logger = logging.getLogger(__name__)

# Yahoo!ファイナンス（日本版）のページタイトルからHTMLをパースせず銘柄名を
# 抜き出すための簡易正規表現（フルHTMLパーサーを使うほどではないため）
_YAHOO_JP_TITLE_RE = re.compile(r"<title>([^<]*)</title>")


# アプリ内で使われる最大期間（1mo/6mo/1y/2y/3y/5y）。鮮度切れ時は常にこの期間で
# yfinanceから取得してDBへ蓄積することで、以後どの期間で要求されてもDBだけで
# 足りるようにする（呼び出しごとに異なる期間を要求されても再フェッチが不要になる）。
_MAX_FETCH_PERIOD = "5y"
_PERIOD_TO_DAYS = {
    "1mo": 31,
    "6mo": 186,
    "1y": 366,
    "2y": 731,
    "3y": 1096,
    "5y": 1827,
}


def _period_to_start_date(period: str) -> datetime.date:
    days = _PERIOD_TO_DAYS.get(period, 366)
    return datetime.date.today() - datetime.timedelta(days=days)


def _fetch_price_history_from_yfinance(ticker_symbol: str, period: str) -> pd.DataFrame:
    """yfinanceから直接株価時系列を取得する（DBを経由しない生の取得処理）。"""
    logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history


def _upsert_price_history(session, ticker_symbol: str, history: pd.DataFrame) -> None:
    """historyの各日付をPriceHistoryへ追記する。既にDBにある日付は上書きしない
    （時系列を蓄積する方針のため）。"""
    if history.empty:
        return
    existing_dates = {
        row.date
        for row in session.query(PriceHistory.date).filter_by(ticker=ticker_symbol).all()
    }
    for index, row in history.iterrows():
        date_str = index.date().isoformat() if hasattr(index, "date") else str(index)
        if date_str in existing_dates:
            continue
        session.add(
            PriceHistory(
                ticker=ticker_symbol,
                date=date_str,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
        )
        existing_dates.add(date_str)


def _load_price_history_from_db(session, ticker_symbol: str, period: str) -> pd.DataFrame:
    start_date = _period_to_start_date(period).isoformat()
    rows = (
        session.query(PriceHistory)
        .filter(PriceHistory.ticker == ticker_symbol, PriceHistory.date >= start_date)
        .order_by(PriceHistory.date)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return pd.DataFrame(
        {
            "Open": [r.open for r in rows],
            "High": [r.high for r in rows],
            "Low": [r.low for r in rows],
            "Close": [r.close for r in rows],
            "Volume": [r.volume for r in rows],
        },
        index=pd.to_datetime([r.date for r in rows]),
    )


def fetch_price_history(
    ticker_symbol: str, period: str = "1mo", session_factory=SessionLocal
) -> pd.DataFrame:
    """指定銘柄の株価時系列（OHLCV）を取得する。DB上の当該銘柄の最新日付が
    「本日から1日以内」ならDBから期間分を組み立てて返す。それより古い/データ無し
    ならyfinanceから_MAX_FETCH_PERIOD分を取得してPriceHistoryへ追記した上で、
    DBから期間分を組み立てて返す。"""
    with session_factory() as session:
        latest_date_str = (
            session.query(PriceHistory.date)
            .filter_by(ticker=ticker_symbol)
            .order_by(PriceHistory.date.desc())
            .limit(1)
            .scalar()
        )
        is_fresh = latest_date_str is not None and (
            datetime.date.today() - datetime.date.fromisoformat(latest_date_str)
        ).days <= 1

        if not is_fresh:
            history = _fetch_price_history_from_yfinance(ticker_symbol, _MAX_FETCH_PERIOD)
            _upsert_price_history(session, ticker_symbol, history)
            session.commit()

        return _load_price_history_from_db(session, ticker_symbol, period)


def _fetch_fundamentals_from_yfinance(ticker_symbol: str) -> dict:
    """yfinanceから直接ファンダメンタルズ指標を取得する（DBを経由しない生の取得処理）。"""
    logger.info("fundamentalsリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
        "return_on_equity": info.get("returnOnEquity"),
        "revenue_growth": info.get("revenueGrowth"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def _fundamentals_snapshot_to_dict(row: FundamentalsSnapshot) -> dict:
    return {
        "ticker": row.ticker,
        "name": row.name,
        "trailing_pe": row.trailing_pe,
        "price_to_book": row.price_to_book,
        "dividend_yield": row.dividend_yield,
        "market_cap": row.market_cap,
        "return_on_equity": row.return_on_equity,
        "revenue_growth": row.revenue_growth,
    }


def fetch_fundamentals(ticker_symbol: str, session_factory=SessionLocal) -> dict:
    """指定銘柄のファンダメンタルズ指標を取得する。当日分のスナップショットが
    DBにあればそれを返し、無ければyfinanceから取得してDBへ新規スナップショット
    として追加する（同日内は追加取得しない）。"""
    today = datetime.date.today().isoformat()
    with session_factory() as session:
        row = (
            session.query(FundamentalsSnapshot)
            .filter_by(ticker=ticker_symbol, snapshot_date=today)
            .first()
        )
        if row is not None:
            return _fundamentals_snapshot_to_dict(row)

        result = _fetch_fundamentals_from_yfinance(ticker_symbol)
        session.add(
            FundamentalsSnapshot(
                ticker=ticker_symbol,
                snapshot_date=today,
                name=result["name"],
                trailing_pe=result["trailing_pe"],
                price_to_book=result["price_to_book"],
                dividend_yield=result["dividend_yield"],
                market_cap=result["market_cap"],
                return_on_equity=result["return_on_equity"],
                revenue_growth=result["revenue_growth"],
            )
        )
        session.commit()
        return result


_PROFILE_FRESHNESS_DAYS = 30


def _is_stale(updated_at: datetime.datetime | None, max_age_days: int) -> bool:
    if updated_at is None:
        return True
    now = datetime.datetime.now(datetime.timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
    return (now - updated_at).days >= max_age_days


def _fetch_company_profile_from_yfinance(ticker_symbol: str) -> dict:
    """yfinanceから直接業種・事業内容を取得する（DBを経由しない生の取得処理）。"""
    logger.info("company profileリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": info.get("longBusinessSummary"),
    }
    logger.info("company profileレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_company_profile(ticker_symbol: str, session_factory=SessionLocal) -> dict:
    """指定銘柄の業種・事業内容を取得する。CompanyProfile.profile_updated_atが
    _PROFILE_FRESHNESS_DAYS以内ならDBの値を再利用し、無ければ/古ければyfinanceから
    取得してsector/industry/business_summary/profile_updated_atのみ更新する
    （nameカラムはfetch_japanese_nameが管理するため触れない）。"""
    with session_factory() as session:
        row = session.get(CompanyProfile, ticker_symbol)
        if row is not None and not _is_stale(row.profile_updated_at, _PROFILE_FRESHNESS_DAYS):
            return {
                "ticker": ticker_symbol,
                "sector": row.sector,
                "industry": row.industry,
                "business_summary": row.business_summary,
            }

        result = _fetch_company_profile_from_yfinance(ticker_symbol)
        if row is None:
            row = CompanyProfile(ticker=ticker_symbol)
            session.add(row)
        row.sector = result["sector"]
        row.industry = result["industry"]
        row.business_summary = result["business_summary"]
        row.profile_updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return result


def _fetch_news_from_yfinance(ticker_symbol: str, limit: int) -> list[dict]:
    """yfinanceから直接ニュースを取得し、表示に必要な項目だけに整形する
    （DBを経由しない生の取得処理）。"""
    logger.info("newsリクエスト: ticker=%s limit=%s", ticker_symbol, limit)
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    result = []
    for item in news_items[:limit]:
        # yfinanceのニュースレスポンスはネストしたcontent/provider構造のため、
        # 欠損があっても落ちないよう各階層でNone安全に取り出す
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    logger.info("newsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def _insert_new_ticker_news(session, ticker_symbol: str, items: list[dict]) -> None:
    """未知の記事のみTickerNewsへ追記する。linkがある記事は(ticker, link)で、
    linkが無い記事は(ticker, title, publisher)で重複判定する。"""
    existing_links = {
        row.link
        for row in session.query(TickerNews.link)
        .filter_by(ticker=ticker_symbol)
        .filter(TickerNews.link.isnot(None))
        .all()
    }
    existing_no_link = {
        (row.title, row.publisher)
        for row in session.query(TickerNews.title, TickerNews.publisher)
        .filter_by(ticker=ticker_symbol, link=None)
        .all()
    }
    for item in items:
        link = item.get("link")
        if link is not None:
            if link in existing_links:
                continue
            existing_links.add(link)
        else:
            key = (item.get("title"), item.get("publisher"))
            if key in existing_no_link:
                continue
            existing_no_link.add(key)
        session.add(
            TickerNews(
                ticker=ticker_symbol,
                title=item.get("title"),
                publisher=item.get("publisher"),
                link=link,
            )
        )


def fetch_news(ticker_symbol: str, limit: int = 5, session_factory=SessionLocal) -> list[dict]:
    """指定銘柄に関連する最新ニュースを取得する。毎回yfinanceから最新記事を取得して
    未知の記事のみDBへ追記した上で、DBに蓄積された記事から最新limit件を返す
    （複数ユーザーの取得タイミングの違いにより結果的に記事が積み上がる）。"""
    with session_factory() as session:
        fresh_items = _fetch_news_from_yfinance(ticker_symbol, limit)
        _insert_new_ticker_news(session, ticker_symbol, fresh_items)
        session.commit()

        rows = (
            session.query(TickerNews)
            .filter_by(ticker=ticker_symbol)
            .order_by(TickerNews.fetched_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {"title": row.title, "publisher": row.publisher, "link": row.link} for row in rows
        ]


def _fetch_japanese_name_from_source(ticker_symbol: str) -> str | None:
    """Yahoo!ファイナンス（日本版）のページタイトルから直接日本語銘柄名を取得する
    （DBを経由しない生の取得処理）。yfinance（Yahoo Financeのグローバルデータ）は
    日本株の名前を英語でしか返さないため、日本語名専用にこの関数を使う。
    """
    url = f"https://finance.yahoo.co.jp/quote/{ticker_symbol}"
    logger.info("日本語銘柄名リクエスト: url=%s", url)
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("日本語銘柄名取得失敗: url=%s", url)
        return None
    logger.info("日本語銘柄名レスポンス: url=%s body=%s", url, response.text)

    match = _YAHOO_JP_TITLE_RE.search(response.text)
    if not match:
        return None

    title = match.group(1)
    if "【" not in title:
        return None

    name = title.split("【", 1)[0].strip()
    return name or None


def fetch_japanese_name(ticker_symbol: str, session_factory=SessionLocal) -> str | None:
    """指定銘柄の日本語名を取得する。CompanyProfile.name_updated_atが
    _PROFILE_FRESHNESS_DAYS以内ならDBの値を再利用する。取得に失敗した場合は
    DBを更新せずNoneを返す（次回呼び出し時に再試行される）。"""
    with session_factory() as session:
        row = session.get(CompanyProfile, ticker_symbol)
        if (
            row is not None
            and row.name is not None
            and not _is_stale(row.name_updated_at, _PROFILE_FRESHNESS_DAYS)
        ):
            return row.name

        name = _fetch_japanese_name_from_source(ticker_symbol)
        if name is None:
            return None

        if row is None:
            row = CompanyProfile(ticker=ticker_symbol)
            session.add(row)
        row.name = name
        row.name_updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return name


def _to_pct(value: float | None) -> float | None:
    """yfinanceが小数（例: 0.155 = 15.5%）で返す指標を、パーセント表示用に100倍する。"""
    return None if value is None else value * 100


def fetch_universe_fundamentals(
    tickers: list[str],
    session_factory=SessionLocal,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズをまとめて取得し、DataFrameとして返す。

    銘柄ごとの鮮度チェック・DB読み書きはfetch_fundamentals（DB read-through）に
    委譲し、ここでは並行実行（複数銘柄を並行してAPI取得）と結果の整形のみを行う。
    """
    with log_duration(logger, f"ユニバースfundamentals一括取得（{len(tickers)}銘柄）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_fundamentals(ticker, session_factory=session_factory)
        )
        rows = []
        for ticker_symbol in tickers:
            data = results[ticker_symbol]
            # 個別銘柄の取得失敗（例外）は全体を止めず、その銘柄だけスキップする
            if isinstance(data, Exception):
                continue
            rows.append(
                {
                    "ticker": data.get("ticker", ticker_symbol),
                    "name": data.get("name"),
                    "per": data.get("trailing_pe"),
                    "pbr": data.get("price_to_book"),
                    # yfinance's dividendYield is already a percentage number
                    # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                    "dividend_yield_pct": data.get("dividend_yield"),
                    "market_cap": data.get("market_cap"),
                    # returnOnEquity/revenueGrowthは小数（例: 0.155 = 15.5%）で
                    # 返るため、dividend_yieldと異なり100倍してパーセント表示用にする。
                    "roe_pct": _to_pct(data.get("return_on_equity")),
                    "revenue_growth_pct": _to_pct(data.get("revenue_growth")),
                }
            )
        return pd.DataFrame(rows)


def fetch_universe_price_histories(
    tickers: list[str],
    period: str,
    session_factory=SessionLocal,
    fetch_price_history=fetch_price_history,
) -> dict[str, pd.Series]:
    """複数銘柄の終値時系列をまとめて取得し、{ticker: pd.Series} として返す。

    strategy_builderの簡易バックテスト・銘柄選定実行画面で、絞り込み後の
    銘柄群の株価をまとめて取得する用途に使う。銘柄ごとの鮮度チェック・DB読み書きは
    fetch_price_history（DB read-through）に委譲し、ここでは並行実行と結果の整形
    のみを行う。取得失敗・空データの銘柄は結果から除外する。
    """
    with log_duration(logger, f"ユニバース株価一括取得（{len(tickers)}銘柄, period={period}）"):
        results = map_concurrently(
            tickers,
            lambda ticker: fetch_price_history(
                ticker, period=period, session_factory=session_factory
            ),
        )
        prices_by_ticker: dict[str, pd.Series] = {}
        for ticker in tickers:
            history = results[ticker]
            if isinstance(history, Exception) or history is None or history.empty:
                continue
            prices_by_ticker[ticker] = history["Close"]
        return prices_by_ticker
