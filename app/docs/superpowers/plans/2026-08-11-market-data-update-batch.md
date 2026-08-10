# 市場データ定期更新バッチ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `fetch_price_history` に差分取得を追加した上で、`company_profiles` 全銘柄を対象に `price_history`/`fundamentals_snapshots`/`ticker_news` を更新するバッチスクリプトと、それを起動するWindows用`.bat`を追加する。

**Architecture:** (1) `_fetch_price_history_from_yfinance`/`fetch_price_history` に `start_date` パラメータを追加し、既存データがある場合は「最新日付の翌日以降」だけをyfinanceへ問い合わせる（既存データが無い場合は従来通り`_MAX_FETCH_PERIOD`の全量取得）。この変更は既存呼び出し元に対して透過的。(2) 新規 `scripts/update_market_data.py` が `load_all_company_profiles()` で対象ticker一覧を取得し、`map_concurrently` で `fetch_price_history`/`fetch_fundamentals`/`fetch_news` を並行実行、銘柄ごとの成否をログ・サマリー化する。(3) `scripts/update_market_data.bat` がPythonスクリプトを起動する薄いラッパー。

**Tech Stack:** Python, SQLAlchemy, pytest, yfinance, 既存の`common.concurrency.map_concurrently`/`common.logging_config`

## Global Constraints

- `fetch_price_history`の外部シグネチャ・戻り値は変更しない（内部実装のみの変更）。
- 途中欠損の自己修復が失われるトレードオフは容認済み（設計参照）。追加のフルリシンク機構は実装しない。
- バッチは`fetch_universe_fundamentals`/`fetch_universe_price_histories`等の既存の一括ヘルパーを使わず、`map_concurrently`を直接使う（失敗銘柄を個別にログするため）。
- 既存のテストスタイル（`monkeypatch` + `FakeTicker`、`tmp_path` + `create_db_engine` + `init_db` + `sessionmaker`）に合わせる。

---

## File Structure

- Modify: `data_api/stock_price_api.py` — `_fetch_price_history_from_yfinance`/`fetch_price_history`に差分取得を追加
- Modify: `tests/test_stock_price_api.py` — `FakeTicker`/`CountingTicker`のモック更新、差分取得の新規テスト
- Create: `scripts/update_market_data.py` — `run_update()`/`main()`
- Create: `tests/test_update_market_data.py`
- Create: `scripts/update_market_data.bat`

---

### Task 1: `fetch_price_history`に差分取得を追加する

**Files:**
- Modify: `data_api/stock_price_api.py`
- Modify: `tests/test_stock_price_api.py`

**Interfaces:**
- Produces: `_fetch_price_history_from_yfinance(ticker_symbol: str, period: str | None = None, start_date: datetime.date | None = None) -> pd.DataFrame`。`fetch_price_history`の外部シグネチャ・戻り値は不変。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_price_api.py` の末尾に追加:

```python
def test_fetch_price_history_uses_incremental_start_date_when_stale_data_exists(
    monkeypatch, tmp_path
):
    captured_calls = []

    class RecordingTicker(FakeTicker):
        def history(self, period=None, start=None):
            captured_calls.append({"period": period, "start": start})
            return super().history()

    monkeypatch.setattr(stock_price_api.yf, "Ticker", RecordingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    old_date = datetime.date.today() - datetime.timedelta(days=10)
    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="TEST1.T"))
        session.add(
            stock_price_api.PriceHistory(
                ticker="TEST1.T",
                date=old_date.isoformat(),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        )
        session.commit()

    stock_price_api.fetch_price_history("TEST1.T", session_factory=session_factory)

    assert len(captured_calls) == 1
    assert captured_calls[0]["period"] is None
    assert captured_calls[0]["start"] == (old_date + datetime.timedelta(days=1)).isoformat()


def test_fetch_price_history_uses_full_period_when_no_existing_data(monkeypatch, tmp_path):
    captured_calls = []

    class RecordingTicker(FakeTicker):
        def history(self, period=None, start=None):
            captured_calls.append({"period": period, "start": start})
            return super().history()

    monkeypatch.setattr(stock_price_api.yf, "Ticker", RecordingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("TEST1.T", session_factory=session_factory)

    assert len(captured_calls) == 1
    assert captured_calls[0]["start"] is None
    assert captured_calls[0]["period"] == stock_price_api._MAX_FETCH_PERIOD
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_stock_price_api.py -k incremental_start_date -v`
Expected: FAIL（`fetch_price_history`は常に`period=_MAX_FETCH_PERIOD`で呼ぶため、`test_..._when_stale_data_exists`は`captured_calls[0]["period"]`が`None`でなく`"5y"`になり失敗する。`test_..._no_existing_data`は現時点でも偶然PASSする可能性があるが、Step3実装後も両方PASSすることを最終確認する）

- [ ] **Step 3: `data_api/stock_price_api.py`を修正する**

`_fetch_price_history_from_yfinance`を修正:

```python
def _fetch_price_history_from_yfinance(
    ticker_symbol: str, period: str | None = None, start_date: datetime.date | None = None
) -> pd.DataFrame:
    """yfinanceから直接株価時系列を取得する（DBを経由しない生の取得処理）。
    start_date指定時はその日付以降のみを取得する差分取得、未指定時は
    period分をまとめて取得する全量取得になる。"""
    ticker = yf.Ticker(ticker_symbol)
    if start_date is not None:
        logger.info(
            "株価履歴リクエスト（差分）: ticker=%s start_date=%s", ticker_symbol, start_date
        )
        history = ticker.history(start=start_date.isoformat())
    else:
        logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
        history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history
```

`fetch_price_history`を修正:

```python
def fetch_price_history(
    ticker_symbol: str, period: str = "1mo", session_factory=SessionLocal
) -> pd.DataFrame:
    """指定銘柄の株価時系列（OHLCV）を取得する。DB上の当該銘柄の最新日付が
    「本日から1日以内」ならDBから期間分を組み立てて返す。それより古い場合、
    既存データが無ければ_MAX_FETCH_PERIOD分をまとめて取得し、既存データが
    あればその翌日以降のみを差分取得してPriceHistoryへ追記した上で、
    DBから期間分を組み立てて返す（途中の欠損は自己修復しない。管理者が
    行を削除した場合等は当該tickerの全件削除で全量バックフィルに戻せる）。"""
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
            if latest_date_str is None:
                history = _fetch_price_history_from_yfinance(
                    ticker_symbol, period=_MAX_FETCH_PERIOD
                )
            else:
                start_date = datetime.date.fromisoformat(
                    latest_date_str
                ) + datetime.timedelta(days=1)
                history = _fetch_price_history_from_yfinance(
                    ticker_symbol, start_date=start_date
                )
            _upsert_price_history(session, ticker_symbol, history)
            session.commit()

        return _load_price_history_from_db(session, ticker_symbol, period)
```

- [ ] **Step 4: 既存モックのシグネチャを更新する**

`tests/test_stock_price_api.py`の`FakeTicker.history`を修正:

```python
    def history(self, period=None, start=None):
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=3, freq="D")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [105.0, 106.0, 107.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.0, 101.0, 102.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=dates,
        )
```

`test_fetch_price_history_reuses_db_on_second_call`内の`CountingTicker.history`を修正:

```python
    class CountingTicker(FakeTicker):
        def history(self, period=None, start=None):
            call_count["n"] += 1
            return super().history(period=period, start=start)
```

`test_fetch_price_history_refetches_when_stale`内の`CountingTicker.history`も同様に修正:

```python
    class CountingTicker(FakeTicker):
        def history(self, period=None, start=None):
            call_count["n"] += 1
            return super().history(period=period, start=start)
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_stock_price_api.py -v`
Expected: PASS（全件）

- [ ] **Step 6: コミット**

```bash
git add app/data_api/stock_price_api.py app/tests/test_stock_price_api.py
git commit -m "feat: fetch price history incrementally from the latest stored date"
```

---

### Task 2: 市場データ更新バッチスクリプト

**Files:**
- Create: `scripts/update_market_data.py`
- Create: `tests/test_update_market_data.py`

**Interfaces:**
- Consumes: `data_api.stock_price_api.load_all_company_profiles`/`fetch_price_history`/`fetch_fundamentals`/`fetch_news`、`db.engine.engine`/`init_db`、`common.logging_config.setup_logging`/`log_duration`、`common.concurrency.map_concurrently`
- Produces: `run_update(session_factory=SessionLocal) -> dict`（`{"price_history": {"success": int, "failed": list[str]}, "fundamentals": {...}, "news": {...}}`）。`main() -> None`（`run_update()`を呼び、失敗が1件でもあれば`sys.exit(1)`、無ければ`sys.exit(0)`）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_update_market_data.py`（新規）:

```python
import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import CompanyProfile
from scripts.update_market_data import main, run_update


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine)
    # init_db()はseed_company_profiles.csvから228件のcompany_profilesを自動投入
    # するため、このテストファイルが対象ticker集合を厳密に制御できるよう
    # 一旦全件削除しておく（この時点ではprice_history等の子行はまだ無いため
    # FK違反は起きない）。
    with factory() as session:
        session.query(CompanyProfile).delete()
        session.commit()
    return factory


def _seed_tickers(session_factory, tickers):
    with session_factory() as session:
        for ticker in tickers:
            session.add(CompanyProfile(ticker=ticker))
        session.commit()


def test_run_update_calls_fetch_functions_for_every_company_profile_ticker(
    monkeypatch, session_factory
):
    _seed_tickers(session_factory, ["AAAA.T", "BBBB.T"])

    called_price = []
    called_fundamentals = []
    called_news = []

    def fake_fetch_price_history(ticker, session_factory=None):
        called_price.append(ticker)
        return pd.DataFrame()

    def fake_fetch_fundamentals(ticker, session_factory=None):
        called_fundamentals.append(ticker)
        return {}

    def fake_fetch_news(ticker, session_factory=None):
        called_news.append(ticker)
        return []

    monkeypatch.setattr(
        "scripts.update_market_data.fetch_price_history", fake_fetch_price_history
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals", fake_fetch_fundamentals
    )
    monkeypatch.setattr("scripts.update_market_data.fetch_news", fake_fetch_news)

    summary = run_update(session_factory=session_factory)

    assert sorted(called_price) == ["AAAA.T", "BBBB.T"]
    assert sorted(called_fundamentals) == ["AAAA.T", "BBBB.T"]
    assert sorted(called_news) == ["AAAA.T", "BBBB.T"]
    assert summary["price_history"]["success"] == 2
    assert summary["fundamentals"]["success"] == 2
    assert summary["news"]["success"] == 2
    assert summary["price_history"]["failed"] == []


def test_run_update_records_failures_without_stopping_other_tickers(
    monkeypatch, session_factory
):
    _seed_tickers(session_factory, ["AAAA.T", "BBBB.T"])

    def flaky_fetch_price_history(ticker, session_factory=None):
        if ticker == "AAAA.T":
            raise RuntimeError("boom")
        return pd.DataFrame()

    monkeypatch.setattr(
        "scripts.update_market_data.fetch_price_history", flaky_fetch_price_history
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals",
        lambda ticker, session_factory=None: {},
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_news", lambda ticker, session_factory=None: []
    )

    summary = run_update(session_factory=session_factory)

    assert summary["price_history"]["success"] == 1
    assert summary["price_history"]["failed"] == ["AAAA.T"]
    assert summary["fundamentals"]["success"] == 2
    assert summary["news"]["success"] == 2


def test_main_exits_zero_when_all_succeed(monkeypatch, session_factory):
    _seed_tickers(session_factory, ["AAAA.T"])
    monkeypatch.setattr(
        "scripts.update_market_data.SessionLocal", session_factory
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_price_history",
        lambda ticker, session_factory=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals",
        lambda ticker, session_factory=None: {},
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_news", lambda ticker, session_factory=None: []
    )
    monkeypatch.setattr("scripts.update_market_data.init_db", lambda engine: None)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_exits_one_when_any_ticker_fails(monkeypatch, session_factory):
    _seed_tickers(session_factory, ["AAAA.T"])
    monkeypatch.setattr(
        "scripts.update_market_data.SessionLocal", session_factory
    )

    def failing_fetch(ticker, session_factory=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("scripts.update_market_data.fetch_price_history", failing_fetch)
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals",
        lambda ticker, session_factory=None: {},
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_news", lambda ticker, session_factory=None: []
    )
    monkeypatch.setattr("scripts.update_market_data.init_db", lambda engine: None)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_update_market_data.py -v`
Expected: FAIL（`scripts.update_market_data`モジュールが存在しないため`ModuleNotFoundError`）

- [ ] **Step 3: `scripts/update_market_data.py`を実装する**

```python
"""company_profilesに登録された全銘柄を対象に、price_history/
fundamentals_snapshots/ticker_newsを更新するバッチ。Windowsタスク
スケジューラ等から`update_market_data.bat`経由で定期実行する想定。

実行方法（ai-stock-investing-tutorial/app ディレクトリで）:
    uv run python -m scripts.update_market_data
"""

import logging
import sys

from common.concurrency import map_concurrently
from common.logging_config import log_duration, setup_logging
from data_api.stock_price_api import (
    fetch_fundamentals,
    fetch_news,
    fetch_price_history,
    load_all_company_profiles,
)
from db.engine import SessionLocal, engine, init_db

logger = logging.getLogger(__name__)


def _run_phase(phase_name: str, tickers: list[str], fetch_fn, session_factory) -> dict:
    """1データ種別（price_history/fundamentals/news）について、対象ticker全件を
    並行取得する。1銘柄の失敗が他銘柄の処理を止めないよう、失敗はtickerと
    例外内容をログした上でサマリーに記録し、処理は継続する。"""
    with log_duration(logger, f"{phase_name}更新（{len(tickers)}銘柄）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_fn(ticker, session_factory=session_factory)
        )
        failed = []
        for ticker in tickers:
            result = results[ticker]
            if isinstance(result, Exception):
                failed.append(ticker)
                logger.warning(
                    "%s取得失敗: ticker=%s error=%s", phase_name, ticker, result
                )
        success = len(tickers) - len(failed)
        logger.info(
            "%s更新完了: 成功%d件 / 失敗%d件", phase_name, success, len(failed)
        )
        return {"success": success, "failed": failed}


def run_update(session_factory=SessionLocal) -> dict:
    """company_profiles全銘柄のprice_history/fundamentals_snapshots/ticker_news
    を更新し、データ種別ごとの成功件数・失敗ticker一覧を返す。"""
    tickers = [p["ticker"] for p in load_all_company_profiles(session_factory=session_factory)]
    logger.info("市場データ更新バッチ開始: 対象%d銘柄", len(tickers))

    summary = {
        "price_history": _run_phase(
            "price_history", tickers, fetch_price_history, session_factory
        ),
        "fundamentals": _run_phase(
            "fundamentals", tickers, fetch_fundamentals, session_factory
        ),
        "news": _run_phase("news", tickers, fetch_news, session_factory),
    }
    return summary


def main() -> None:
    setup_logging()
    init_db(engine)
    # run_update()のデフォルト引数（session_factory=SessionLocal）はモジュール
    # import時に束縛されテスト側からのmonkeypatchが効かないため、呼び出し時に
    # SessionLocalをこの関数本体内で改めて参照する（呼び出し時のグローバル
    # 参照になりmonkeypatch.setattrで差し替え可能になる）。
    summary = run_update(session_factory=SessionLocal)
    any_failed = any(phase["failed"] for phase in summary.values())
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_update_market_data.py -v`
Expected: PASS（全5件）

- [ ] **Step 5: コミット**

```bash
git add app/scripts/update_market_data.py app/tests/test_update_market_data.py
git commit -m "feat: add market data update batch script"
```

---

### Task 3: 起動用`.bat`

**Files:**
- Create: `scripts/update_market_data.bat`

- [ ] **Step 1: `.bat`を作成する**

```bat
@echo off
cd /d %~dp0..
uv run python -m scripts.update_market_data
exit /b %errorlevel%
```

- [ ] **Step 2: 実際に実行して動作確認する**

Run: `cd app && scripts\update_market_data.bat`
Expected: `app/logs/app.log`に「市場データ更新バッチ開始」「price_history更新完了」等のログが出力され、コマンドの終了コードが0（`echo %errorlevel%`で確認）。company_profilesの全銘柄分の実データ取得が走るため数分かかる可能性がある点に留意する。

- [ ] **Step 3: コミット**

```bash
git add app/scripts/update_market_data.bat
git commit -m "feat: add .bat launcher for the market data update batch"
```

---

### Task 4: 全体テスト確認

**Files:** なし（検証のみ）

- [ ] **Step 1: 全テストを実行する**

Run: `cd app && python -m pytest -v`
Expected: PASS（全件。他モジュールへの回帰が無いことを確認する）

- [ ] **Step 2: 本番DBへの影響確認**

`app/data/app.db`は今回のタスクでは自動実行しない（`.bat`を手動実行するまでは何も変わらない）。Task 3 Step 2で実際に`.bat`を実行する場合のみ本番DBが更新されるため、実行前にバックアップを推奨する旨をユーザーに案内する。
