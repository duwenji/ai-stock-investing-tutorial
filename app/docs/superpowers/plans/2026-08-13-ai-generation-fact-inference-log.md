# 事実情報とAI推論情報の記録・区別（AI生成ログ基盤） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM呼び出しのたびに「入力した事実情報（facts）」と「LLMの見解・推論（ai_output）」をDBへ分離して記録する基盤を実装し、銘柄詳細コメント・AI戦略ビルダー対話の2箇所に組み込み、管理画面に最小限の一覧を表示する。

**Architecture:** 新規テーブル`ai_sessions`（複数回のLLM呼び出しをまとめる単位）と`ai_generations`（個々の呼び出しごとのfacts/prompt/ai_output）を追加し、共通ロガー`common/ai_generation_log.log_ai_generation()`を全呼び出し箇所から呼ぶ。単発生成（銘柄詳細コメント）は1回の生成につき新規セッションを発行し、複数ターンのやり取り（AI戦略ビルダーの対話・Evaluator-Optimizerループ）は同一セッションIDを使い回して連番の`turn_index`で記録する。

**Tech Stack:** Python 3, SQLAlchemy ORM（既存の`db/engine.py`のSQLite構成を再利用）, pytest, Streamlit（UI層のみ・自動テスト対象外）

## Global Constraints

- 新規テーブルのため`db/engine.py`の`_add_column_if_missing`方式は使わない。`Base.metadata.create_all`（既存の`init_db()`）で自動作成される。
- 既存のDI規約に従う: DBアクセス関数はすべて`session_factory=SessionLocal`をキーワード引数で受け取り、テストではインメモリ/一時ファイルSQLiteに差し替える（`db.engine.create_db_engine` + `init_db` + `sqlalchemy.orm.sessionmaker`）。LLM呼び出しは`call_llm=default_call_llm`パターンを維持する。
- `stock_detail/detail.py`と`strategy_builder/evaluation.py`は`st.*`に直接依存しない既存方針を維持する。Streamlit依存はすべて`app_tabs/*.py`側に閉じる。
- `app_tabs/*.py`（UI描画コード）はこのプロジェクトの慣習上、自動テスト対象外。該当タスクでは手動確認手順を明記する。
- 既存のテストが本番DB（`data/app.db`）へ書き込んでしまわないよう、ロギングを追加するすべての既存テスト呼び出しに`session_factory`（一時ファイルSQLite）を明示的に渡す。

---

## Task 1: `ai_sessions`/`ai_generations`テーブルの追加

**Files:**
- Modify: `db/models.py`（末尾に2クラス追加）
- Modify: `tests/test_db_engine.py:18-31`（テーブル名一覧に追加）

**Interfaces:**
- Produces: `db.models.AiSession`（`id: str PK`, `feature: str`, `ticker: str | None`, `user_id: int | None`, `started_at: datetime`）、`db.models.AiGeneration`（`id: int PK`, `session_id: str FK→ai_sessions.id`, `turn_index: int`, `feature: str`, `facts: str(JSON)`, `prompt: str`, `ai_output: str`, `created_at: datetime`）

- [ ] **Step 1: `db/models.py`にモデルを追加**

`TickerNews`クラス（127行目）の後に追記する:

```python
class AiSession(Base):
    __tablename__ = "ai_sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    feature: Mapped[str] = mapped_column(nullable=False)
    ticker: Mapped[str | None] = mapped_column(nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)


class AiGeneration(Base):
    __tablename__ = "ai_generations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("ai_sessions.id"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(nullable=False, default=0)
    feature: Mapped[str] = mapped_column(nullable=False)
    facts: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    ai_output: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)
```

`ticker`は`company_profiles`へのFK制約を付けない（監査ログが銘柄マスタのライフサイクルに引きずられないようにするため）。`user_id`は他テーブル（`Holding`/`Strategy`）と同様に`users.id`へのFKとする。

- [ ] **Step 2: `tests/test_db_engine.py`のテーブル一覧を更新**

`test_init_db_creates_all_tables`のセット（21-31行目）に`"ai_sessions"`, `"ai_generations"`を追加する:

```python
def test_init_db_creates_all_tables(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    table_names = set(inspect(engine).get_table_names())
    assert {
        "users",
        "holdings",
        "strategies",
        "sector_display_settings",
        "price_history",
        "fundamentals_snapshots",
        "company_profiles",
        "ticker_news",
        "ai_sessions",
        "ai_generations",
    } <= table_names
```

- [ ] **Step 3: テスト実行**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_db_engine.py -v`
Expected: PASS（新規2テーブルが作成されることを確認）

- [ ] **Step 4: Commit**

```bash
git add db/models.py tests/test_db_engine.py
git commit -m "feat: ai_sessions/ai_generationsテーブルを追加"
```

---

## Task 2: 共通ロガー `common/ai_generation_log.py`

**Files:**
- Create: `common/ai_generation_log.py`
- Test: `tests/test_ai_generation_log.py`

**Interfaces:**
- Consumes: `db.engine.SessionLocal`, `db.models.AiSession`, `db.models.AiGeneration`
- Produces: `log_ai_generation(session_id: str, feature: str, facts: dict, prompt: str, ai_output: str, *, turn_index: int = 0, ticker: str | None = None, user_id: int | None = None, session_feature: str | None = None, session_factory=SessionLocal) -> None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ai_generation_log.py`を新規作成:

```python
import json

import pytest
from sqlalchemy.orm import sessionmaker

from common.ai_generation_log import log_ai_generation
from db.engine import create_db_engine, init_db
from db.models import AiGeneration, AiSession


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ai_log.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_log_ai_generation_creates_session_and_generation_on_first_call(session_factory):
    log_ai_generation(
        "session-1",
        "stock_detail_comment",
        facts={"per": 12.0},
        prompt="銘柄について教えて",
        ai_output="AIの回答です",
        turn_index=0,
        ticker="AAA.T",
        user_id=5,
        session_feature="stock_detail",
        session_factory=session_factory,
    )

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == "session-1"
        assert sessions[0].feature == "stock_detail"
        assert sessions[0].ticker == "AAA.T"
        assert sessions[0].user_id == 5

        generations = session.query(AiGeneration).all()
        assert len(generations) == 1
        generation = generations[0]
        assert generation.session_id == "session-1"
        assert generation.turn_index == 0
        assert generation.feature == "stock_detail_comment"
        assert json.loads(generation.facts) == {"per": 12.0}
        assert generation.prompt == "銘柄について教えて"
        assert generation.ai_output == "AIの回答です"


def test_log_ai_generation_reuses_existing_session_on_second_call(session_factory):
    log_ai_generation(
        "session-1",
        "stock_detail_comment",
        facts={"per": 12.0},
        prompt="p1",
        ai_output="a1",
        turn_index=0,
        session_factory=session_factory,
    )
    log_ai_generation(
        "session-1",
        "stock_detail_profile",
        facts={"sector": "Tech"},
        prompt="p2",
        ai_output="a2",
        turn_index=1,
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.query(AiSession).count() == 1
        generations = session.query(AiGeneration).order_by(AiGeneration.turn_index).all()
        assert len(generations) == 2
        assert generations[0].turn_index == 0
        assert generations[1].turn_index == 1
        assert generations[0].session_id == generations[1].session_id == "session-1"


def test_log_ai_generation_defaults_session_feature_to_feature_when_omitted(session_factory):
    log_ai_generation(
        "session-1",
        "strategy_evaluate",
        facts={"strategy": {}},
        prompt="p",
        ai_output="a",
        session_factory=session_factory,
    )

    with session_factory() as session:
        session_row = session.get(AiSession, "session-1")
        assert session_row.feature == "strategy_evaluate"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_ai_generation_log.py -v`
Expected: FAIL（`common.ai_generation_log`モジュールが存在しない）

- [ ] **Step 3: 実装を書く**

`common/ai_generation_log.py`を新規作成:

```python
"""LLM呼び出しごとに、入力した事実情報（facts）とLLMの応答（ai_output）を
db.models.AiSession/AiGenerationへ分離して記録する共通ロガー。

同一session_idへの初回呼び出し時にai_sessions行を作成し、以降の呼び出しは
既存のセッションにai_generations行を積み増していく。"""
import json

from db.engine import SessionLocal
from db.models import AiGeneration, AiSession


def log_ai_generation(
    session_id: str,
    feature: str,
    facts: dict,
    prompt: str,
    ai_output: str,
    *,
    turn_index: int = 0,
    ticker: str | None = None,
    user_id: int | None = None,
    session_feature: str | None = None,
    session_factory=SessionLocal,
) -> None:
    with session_factory() as session:
        if session.get(AiSession, session_id) is None:
            session.add(
                AiSession(
                    id=session_id,
                    feature=session_feature or feature,
                    ticker=ticker,
                    user_id=user_id,
                )
            )
        session.add(
            AiGeneration(
                session_id=session_id,
                turn_index=turn_index,
                feature=feature,
                facts=json.dumps(facts, ensure_ascii=False, default=str),
                prompt=prompt,
                ai_output=ai_output,
            )
        )
        session.commit()
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_ai_generation_log.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add common/ai_generation_log.py tests/test_ai_generation_log.py
git commit -m "feat: 事実情報とAI応答を分離記録する共通ロガーを追加"
```

---

## Task 3: 銘柄詳細コメント生成へのロギング組み込み

**Files:**
- Modify: `stock_detail/detail.py`
- Modify: `tests/test_stock_detail.py`（全面書き換え: 既存11テストに`session_factory`を追加、新規3テストを追加）

**Interfaces:**
- Consumes: `common.ai_generation_log.log_ai_generation`（Task 2）
- Produces: `generate_stock_detail(..., user_id: int | None = None, session_factory=SessionLocal) -> dict`（戻り値の構造は変更なし。LLM実呼び出し時のみ`ai_sessions`/`ai_generations`へ記録し、キャッシュヒット時は記録しない）

- [ ] **Step 1: `stock_detail/detail.py`を修正**

インポートに追加（19行目付近、既存の`prompt_patterns.stock_detail`インポートの後）:

```python
import uuid

from common.ai_generation_log import log_ai_generation
from db.engine import SessionLocal
```

関数シグネチャ（36-46行目）を変更:

```python
def generate_stock_detail(
    ticker: str,
    name: str | None,
    cache_dir: Path,
    call_llm=default_call_llm,
    fetch_price_history=default_fetch_price_history,
    fetch_news=default_fetch_news,
    analyze_fundamentals=default_analyze_fundamentals,
    analyze_technical=default_analyze_technical,
    fetch_company_profile=default_fetch_company_profile,
    user_id: int | None = None,
    session_factory=SessionLocal,
) -> dict:
```

総合コメント生成部分（139-140行目）を変更:

```python
        prompt = build_stock_detail_prompt(ticker, name, fundamentals, technical, news)
        comment = call_llm(prompt)
        detail_session_id = uuid.uuid4().hex
        log_ai_generation(
            detail_session_id,
            "stock_detail_comment",
            facts={"fundamentals": fundamentals, "technical": technical, "news": news},
            prompt=prompt,
            ai_output=comment,
            turn_index=0,
            ticker=ticker,
            user_id=user_id,
            session_feature="stock_detail",
            session_factory=session_factory,
        )
```

事業内容コメント部分（142-154行目）を変更:

```python
        business_summary = company_profile.get("business_summary")
        if business_summary:
            profile_prompt = build_company_profile_prompt(
                ticker,
                name,
                company_profile.get("sector"),
                company_profile.get("industry"),
                business_summary,
            )
            profile_comment = call_llm(profile_prompt)
            log_ai_generation(
                detail_session_id,
                "stock_detail_profile",
                facts={
                    "sector": company_profile.get("sector"),
                    "industry": company_profile.get("industry"),
                    "business_summary": business_summary,
                },
                prompt=profile_prompt,
                ai_output=profile_comment,
                turn_index=1,
                ticker=ticker,
                user_id=user_id,
                session_factory=session_factory,
            )
        else:
            profile_comment = _NO_PROFILE_MESSAGE
```

- [ ] **Step 2: `tests/test_stock_detail.py`を全面書き換え**

以下の内容で丸ごと置き換える（既存の全テストに`session_factory`フィクスチャ経由の一時DBを渡し、末尾に3テストを追加）:

```python
import json
import logging

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from common.cache import write_cache
from db.engine import create_db_engine, init_db
from db.models import AiGeneration, AiSession
from stock_detail.detail import generate_stock_detail


def _fake_history():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [99.0, 100.5, 101.5],
            "High": [101.0, 102.0, 103.0],
            "Low": [98.5, 100.0, 101.0],
            "Close": [100.0, 101.0, 102.0],
            "Volume": [1000, 1200, 900],
        },
        index=dates,
    )


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ai_log.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_generate_stock_detail_builds_payload_from_dependencies(tmp_path, session_factory):
    def fake_call_llm(prompt):
        if "タイトルを日本語に翻訳してください" in prompt:
            return "ニュース1"
        if "ニュース要約" in prompt:
            return "要約日本語"
        if "市場での立ち位置" in prompt:
            return "テスト用のプロフィール要約です。"
        return "テスト用の総合コメントです。"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "business_summary": "Test business summary.",
        },
        session_factory=session_factory,
    )

    assert result == {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        "technical": {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        "news": [
            {
                "title": "ニュース1",
                "publisher": "社",
                "link": "http://example.com",
                "title_ja": "ニュース1",
            }
        ],
        "comment": "テスト用の総合コメントです。",
        "profile": {
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "profile_comment": "テスト用のプロフィール要約です。",
        },
    }


def test_generate_stock_detail_handles_empty_price_history(tmp_path, session_factory):
    result = generate_stock_detail(
        "AAA.T",
        None,
        tmp_path,
        call_llm=lambda prompt: "コメント",
        fetch_price_history=lambda ticker, period: pd.DataFrame(
            {"Open": [], "High": [], "Low": [], "Close": [], "Volume": []}
        ),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": None, "pbr": None, "dividend_yield": None},
        analyze_technical=lambda history: {"ma_short": None, "ma_long": None, "signal": "データ不足"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": None, "industry": None, "business_summary": None
        },
        session_factory=session_factory,
    )

    assert result["price_history"] == {
        "dates": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    }
    assert result["news"] == []
    assert result["name"] is None
    assert result["profile"]["profile_comment"] == "事業内容の情報が取得できませんでした。"


def test_generate_stock_detail_uses_cache_and_skips_dependency_calls(tmp_path, session_factory):
    call_count = {"n": 0}

    def counting_fetch_price_history(ticker, period):
        call_count["n"] += 1
        return _fake_history()

    generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "初回コメント",
        fetch_price_history=counting_fetch_price_history,
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {
            "ma_short": 1, "ma_long": 1, "signal": "強気", "rsi_series": [1.0]
        },
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )
    assert call_count["n"] == 1

    def fail(*args, **kwargs):
        raise AssertionError("キャッシュヒット時は依存関数が呼ばれてはいけない")

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fail,
        fetch_price_history=fail,
        fetch_news=fail,
        analyze_fundamentals=fail,
        analyze_technical=fail,
        fetch_company_profile=fail,
        session_factory=session_factory,
    )
    assert result["comment"] == "初回コメント"


def test_generate_stock_detail_ignores_stale_cache_missing_ohlcv(tmp_path, session_factory):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00"],
            "close": [100.0],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "旧形式のキャッシュ",
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )

    assert result["comment"] == "再生成後のコメント"
    assert result["price_history"]["open"] == [99.0, 100.5, 101.5]


def test_generate_stock_detail_ignores_stale_cache_missing_profile(tmp_path, session_factory):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "profileキーが無い旧形式のキャッシュ",
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )

    assert result["comment"] == "再生成後のコメント"
    assert "profile" in result


def test_generate_stock_detail_ignores_stale_cache_missing_technical_series(
    tmp_path, session_factory
):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "指標時系列が無い旧形式のキャッシュ",
        "profile": {"sector": "A", "industry": "B", "profile_comment": "C"},
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {
            "ma_short": 1, "ma_long": 1, "signal": "強気", "rsi_series": [1.0]
        },
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )

    assert result["comment"] == "再生成後のコメント"
    assert "rsi_series" in result["technical"]


def test_generate_stock_detail_translates_news_summaries_and_merges_summary_ja(
    tmp_path, session_factory
):
    def fake_call_llm(prompt):
        if "日本語に翻訳してください" in prompt:
            return "翻訳文1@@@翻訳文2"
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {
                "title": "ニュース1",
                "publisher": "社1",
                "link": "http://example.com/1",
                "summary": "Summary 1",
            },
            {
                "title": "ニュース2",
                "publisher": "社2",
                "link": "http://example.com/2",
                "summary": "Summary 2",
            },
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )

    assert result["news"][0]["summary_ja"] == "翻訳文1"
    assert result["news"][1]["summary_ja"] == "翻訳文2"


def test_generate_stock_detail_translates_news_titles_and_summaries(tmp_path, session_factory):
    def fake_call_llm(prompt):
        if "タイトルを日本語に翻訳してください" in prompt:
            return "日本語タイトル1@@@日本語タイトル2"
        if "日本語に翻訳してください" in prompt:
            return "日本語要約1@@@日本語要約2"
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {
                "title": "News 1",
                "publisher": "社1",
                "link": "http://example.com/1",
                "summary": "Summary 1",
            },
            {
                "title": "News 2",
                "publisher": "社2",
                "link": "http://example.com/2",
                "summary": "Summary 2",
            },
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )

    assert result["news"][0]["title_ja"] == "日本語タイトル1"
    assert result["news"][1]["title_ja"] == "日本語タイトル2"
    assert result["news"][0]["summary_ja"] == "日本語要約1"
    assert result["news"][1]["summary_ja"] == "日本語要約2"


def test_generate_stock_detail_skips_summary_translation_call_when_no_news_have_summary(
    tmp_path, session_factory
):
    def fake_call_llm(prompt):
        if "ニュースタイトル" in prompt:
            return "日本語タイトル"
        if "ニュース要約" in prompt:
            raise AssertionError("要約翻訳は呼ばない")
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )

    assert result["news"][0]["title_ja"] == "日本語タイトル"
    assert "summary_ja" not in result["news"][0]


def test_generate_stock_detail_leaves_summary_ja_unset_when_translation_count_mismatches(
    tmp_path, caplog, session_factory
):
    def fake_call_llm(prompt):
        if "日本語に翻訳してください" in prompt:
            return "翻訳文1"  # 2件を渡したのに1件しか返さない異常応答を模す
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    with caplog.at_level(logging.WARNING, logger="stock_detail.detail"):
        result = generate_stock_detail(
            "AAA.T",
            "エーエー株式会社",
            tmp_path,
            call_llm=fake_call_llm,
            fetch_price_history=lambda ticker, period: _fake_history(),
            fetch_news=lambda ticker: [
                {
                    "title": "ニュース1",
                    "publisher": "社1",
                    "link": "http://example.com/1",
                    "summary": "Summary 1",
                },
                {
                    "title": "ニュース2",
                    "publisher": "社2",
                    "link": "http://example.com/2",
                    "summary": "Summary 2",
                },
            ],
            analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
            analyze_technical=lambda history: {
                "ma_short": 101.0, "ma_long": 100.0, "signal": "強気"
            },
            fetch_company_profile=lambda ticker: {
                "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
            },
            session_factory=session_factory,
        )

    assert "summary_ja" not in result["news"][0]
    assert "summary_ja" not in result["news"][1]
    assert "一致しませんでした" in caplog.text


def test_generate_stock_detail_logs_duration_on_cache_miss(tmp_path, caplog, session_factory):
    with caplog.at_level(logging.INFO, logger="stock_detail.detail"):
        generate_stock_detail(
            "AAA.T",
            "エーエー株式会社",
            tmp_path,
            call_llm=lambda prompt: "コメント",
            fetch_price_history=lambda ticker, period: _fake_history(),
            fetch_news=lambda ticker: [],
            analyze_fundamentals=lambda ticker: {},
            analyze_technical=lambda history: {},
            fetch_company_profile=lambda ticker: {
                "ticker": ticker, "sector": None, "industry": None, "business_summary": None
            },
            session_factory=session_factory,
        )

    assert "銘柄詳細生成（AAA.T）" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_generate_stock_detail_logs_comment_and_profile_facts_and_ai_output_separately(
    tmp_path, session_factory
):
    def fake_call_llm(prompt):
        if "市場での立ち位置" in prompt:
            return "プロフィールのAI見解"
        return "総合コメントのAI見解"

    generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
        user_id=7,
    )

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].feature == "stock_detail"
        assert sessions[0].ticker == "AAA.T"
        assert sessions[0].user_id == 7

        generations = session.query(AiGeneration).order_by(AiGeneration.turn_index).all()
        assert [g.feature for g in generations] == [
            "stock_detail_comment",
            "stock_detail_profile",
        ]
        assert [g.turn_index for g in generations] == [0, 1]
        assert generations[0].ai_output == "総合コメントのAI見解"
        assert json.loads(generations[0].facts)["fundamentals"]["per"] == 12.0
        assert generations[1].ai_output == "プロフィールのAI見解"
        assert json.loads(generations[1].facts)["business_summary"] == "C"
        assert generations[0].session_id == generations[1].session_id == sessions[0].id


def test_generate_stock_detail_logs_only_comment_when_no_business_summary(
    tmp_path, session_factory
):
    generate_stock_detail(
        "AAA.T",
        None,
        tmp_path,
        call_llm=lambda prompt: "総合コメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": None, "pbr": None, "dividend_yield": None},
        analyze_technical=lambda history: {"ma_short": None, "ma_long": None, "signal": "データ不足"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": None, "industry": None, "business_summary": None
        },
        session_factory=session_factory,
    )

    with session_factory() as session:
        generations = session.query(AiGeneration).all()
        assert len(generations) == 1
        assert generations[0].feature == "stock_detail_comment"


def test_generate_stock_detail_does_not_log_on_cache_hit(tmp_path, session_factory):
    generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "初回コメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {
            "ma_short": 1, "ma_long": 1, "signal": "強気", "rsi_series": [1.0]
        },
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
        session_factory=session_factory,
    )
    with session_factory() as session:
        first_count = session.query(AiGeneration).count()

    def fail(*args, **kwargs):
        raise AssertionError("キャッシュヒット時は依存関数が呼ばれてはいけない")

    generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fail,
        fetch_price_history=fail,
        fetch_news=fail,
        analyze_fundamentals=fail,
        analyze_technical=fail,
        fetch_company_profile=fail,
        session_factory=session_factory,
    )
    with session_factory() as session:
        second_count = session.query(AiGeneration).count()

    assert first_count == 2
    assert second_count == 2
```

- [ ] **Step 3: テスト実行**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_stock_detail.py -v`
Expected: PASS（全14テスト）

- [ ] **Step 4: Commit**

```bash
git add stock_detail/detail.py tests/test_stock_detail.py
git commit -m "feat: 銘柄詳細コメント生成に事実/AI応答のロギングを組み込む"
```

---

## Task 4: `show_stock_detail_dialog`からのuser_id受け渡し

**Files:**
- Modify: `app_tabs/shared.py:92`

**Interfaces:**
- Consumes: `stock_detail.detail.generate_stock_detail`（Task 3で`user_id`パラメータ追加済み）、`app_tabs.shared.get_current_user_id`

- [ ] **Step 1: 呼び出しを修正**

`app_tabs/shared.py:92`を変更:

```python
        detail = generate_stock_detail(
            ticker, name, CACHE_DIR, call_llm=call_llm, user_id=get_current_user_id()
        )
```

- [ ] **Step 2: 手動確認**

このファイルはプロジェクトの慣習上自動テスト対象外。以下で手動確認する:

Run: `cd ai-stock-investing-tutorial/app && streamlit run app.py`

1. ログインし、任意のタブから銘柄詳細を開く
2. エラーなく詳細画面が表示されることを確認
3. `data/app.db`を開き（例: `python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('select feature, ticker, user_id from ai_sessions order by started_at desc limit 5').fetchall())"`）、`ai_sessions`に`feature='stock_detail'`の行が、`ai_generations`に`stock_detail_comment`（および事業内容があれば`stock_detail_profile`）の行が記録されていることを確認

- [ ] **Step 3: Commit**

```bash
git add app_tabs/shared.py
git commit -m "feat: 銘柄詳細生成呼び出しにログイン中ユーザーIDを渡す"
```

---

## Task 5: AI戦略ビルダー評価・改善ループへのロギング組み込み

**Files:**
- Modify: `strategy_builder/evaluation.py`
- Modify: `tests/test_strategy_builder_evaluation.py`（全面書き換え）

**Interfaces:**
- Consumes: `common.ai_generation_log.log_ai_generation`（Task 2）
- Produces:
  - `evaluate_strategy(strategy, call_llm=default_call_llm, *, session_id: str | None = None, turn_index: int = 0, user_id: int | None = None, session_factory=SessionLocal) -> dict`（戻り値の形は変更なし: `{"pass": bool, "feedback": str}`）
  - `run_evaluation_loop(strategy, call_llm=default_call_llm, max_iterations: int = 3, *, session_id: str | None = None, turn_index_start: int = 0, user_id: int | None = None, session_factory=SessionLocal) -> dict`（戻り値に新規キー`"next_turn_index": int`が追加される）

- [ ] **Step 1: `strategy_builder/evaluation.py`を全面書き換え**

以下の内容で丸ごと置き換える:

```python
# AI戦略ビルダーが確定候補とした戦略JSONを、確定前に自動評価・改善する
# モジュール（Evaluator-Optimizerパターン）。
import json
import uuid

from common.ai_generation_log import log_ai_generation
from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm
from db.engine import SessionLocal
from prompt_patterns.strategy_dialogue import build_refinement_prompt


def build_evaluate_prompt(strategy: dict) -> str:
    """戦略JSONをLLMに渡し、パラメータの具体性・絞り込みすぎ・断定的な投資助言表現の
    3点をチェックさせるプロンプトを組み立てる。戻り値のJSONは{"pass", "feedback"}のみ。"""
    strategy_json = json.dumps(strategy, ensure_ascii=False, indent=2)
    return (
        "以下は投資戦略のスクリーニング/バックテストパイプライン（JSON）です。\n\n"
        f"{strategy_json}\n\n"
        '次の3つの基準で評価し、{"pass": true/false, "feedback": "..."} '
        "形式のJSONのみを出力してください（説明文やコードブロック記法は不要です）。\n"
        "1. 各ステップのfunction・paramsが具体的か（未指定・曖昧な閾値のまま"
        "残っているparamsがないか）\n"
        "2. 条件数が極端に少なく／多くなく、対象銘柄が0件になりそうな過度な"
        "絞り込みでないか\n"
        "3. 断定的な投資助言表現（例: 「必ず上がる」「今すぐ買うべき」）を"
        "含んでいないか\n\n"
        "3つすべてを満たす場合のみpassをtrueにしてください。"
        "falseの場合、feedbackに具体的な改善点を日本語で1〜2文で書いてください。"
    )


# call_llmを引数として外から差し替え可能にしておくことで、テストコードでは
# 本物のLLM呼び出しの代わりにダミー関数を渡せる（本番はdefault_call_llmが使われる）。
# session_id未指定時はこの呼び出し単体のための使い捨てセッションを自動発行する。
# run_evaluation_loopから呼ばれる場合は、対話全体で共有する既存のsession_idが渡される。
def evaluate_strategy(
    strategy: dict,
    call_llm=default_call_llm,
    *,
    session_id: str | None = None,
    turn_index: int = 0,
    user_id: int | None = None,
    session_factory=SessionLocal,
) -> dict:
    prompt = build_evaluate_prompt(strategy)
    raw = call_llm(prompt)
    try:
        parsed_json = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        parsed_json = None

    # 評価自体が失敗した場合（パース不可・pass欠落）は安全側に倒し、不合格として扱う。
    if not isinstance(parsed_json, dict) or "pass" not in parsed_json:
        result = {"pass": False, "feedback": "評価結果のパースに失敗しました。"}
    else:
        result = {
            "pass": bool(parsed_json.get("pass")),
            "feedback": parsed_json.get("feedback", ""),
        }

    log_ai_generation(
        session_id or uuid.uuid4().hex,
        "strategy_evaluate",
        facts={"strategy": strategy},
        prompt=prompt,
        ai_output=raw,
        turn_index=turn_index,
        user_id=user_id,
        session_factory=session_factory,
    )
    return result


def run_evaluation_loop(
    strategy: dict,
    call_llm=default_call_llm,
    max_iterations: int = 3,
    *,
    session_id: str | None = None,
    turn_index_start: int = 0,
    user_id: int | None = None,
    session_factory=SessionLocal,
) -> dict:
    """evaluate_strategyがpass=Trueを返すかmax_iterationsに達するまで、
    build_refinement_promptによる再生成を繰り返す。

    改善案の応答がJSONとして無効、またはstepsキーを含まない場合は、
    そのイテレーションをスキップし直前のstrategyのままループを継続する。
    最後の評価イテレーションの後には改善案を生成しない。

    session_id未指定時はこのループ全体のための使い捨てセッションを自動発行し、
    評価・改善の全呼び出しをそのセッション内の連番turn_indexで記録する。
    戻り値のnext_turn_indexは、呼び出し元（対話ターン）が続けて同じセッションに
    ログを積み増す際に使うturn_indexの開始値。
    """
    resolved_session_id = session_id or uuid.uuid4().hex
    current = strategy
    last_feedback = None
    turn = turn_index_start
    for i in range(max_iterations):
        evaluation = evaluate_strategy(
            current,
            call_llm=call_llm,
            session_id=resolved_session_id,
            turn_index=turn,
            user_id=user_id,
            session_factory=session_factory,
        )
        turn += 1
        if evaluation["pass"]:
            return {
                "strategy": current,
                "iterations": i,
                "last_feedback": last_feedback,
                "next_turn_index": turn,
            }
        last_feedback = evaluation["feedback"]

        # 最後のイテレーションでは改善案を生成しない（どうせ再評価されないLLM呼び出しを省く）。
        if i < max_iterations - 1:
            refine_prompt = build_refinement_prompt(current, last_feedback)
            raw = call_llm(refine_prompt)
            log_ai_generation(
                resolved_session_id,
                "strategy_refine",
                facts={"strategy": current, "feedback": last_feedback},
                prompt=refine_prompt,
                ai_output=raw,
                turn_index=turn,
                user_id=user_id,
                session_factory=session_factory,
            )
            turn += 1
            try:
                refined = json.loads(strip_code_fence(raw))
            except json.JSONDecodeError:
                refined = None
            if isinstance(refined, dict) and "steps" in refined:
                current = refined

    return {
        "strategy": current,
        "iterations": max_iterations,
        "last_feedback": last_feedback,
        "next_turn_index": turn,
    }
```

- [ ] **Step 2: `tests/test_strategy_builder_evaluation.py`を全面書き換え**

以下の内容で丸ごと置き換える:

```python
import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import AiGeneration, AiSession
from strategy_builder.evaluation import (
    build_evaluate_prompt,
    evaluate_strategy,
    run_evaluation_loop,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ai_log.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_build_evaluate_prompt_includes_strategy_and_criteria():
    strategy = {
        "strategy_name": "割安株",
        "steps": [
            {
                "function": "FILTER_BY_FUNDAMENTALS",
                "params": {"conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}]},
            }
        ],
    }
    prompt = build_evaluate_prompt(strategy)
    assert "割安株" in prompt
    assert "PER" in prompt
    assert "pass" in prompt
    assert "各ステップのfunction・params" in prompt
    assert "断定的な投資助言" in prompt


def test_evaluate_strategy_parses_pass_response(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    result = evaluate_strategy(
        strategy,
        call_llm=lambda prompt: '{"pass": true, "feedback": ""}',
        session_factory=session_factory,
    )
    assert result == {"pass": True, "feedback": ""}


def test_evaluate_strategy_falls_back_to_fail_on_invalid_json(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    result = evaluate_strategy(
        strategy, call_llm=lambda prompt: "not json", session_factory=session_factory
    )
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_evaluate_strategy_falls_back_to_fail_when_pass_key_missing(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    result = evaluate_strategy(
        strategy,
        call_llm=lambda prompt: '{"feedback": "何か"}',
        session_factory=session_factory,
    )
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_evaluate_strategy_logs_facts_prompt_and_ai_output(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    evaluate_strategy(
        strategy,
        call_llm=lambda prompt: '{"pass": true, "feedback": ""}',
        session_id="session-1",
        turn_index=3,
        user_id=9,
        session_factory=session_factory,
    )

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == "session-1"
        assert sessions[0].feature == "strategy_evaluate"
        assert sessions[0].user_id == 9

        generations = session.query(AiGeneration).all()
        assert len(generations) == 1
        assert generations[0].feature == "strategy_evaluate"
        assert generations[0].turn_index == 3
        assert generations[0].session_id == "session-1"
        assert generations[0].ai_output == '{"pass": true, "feedback": ""}'
        assert json.loads(generations[0].facts) == {"strategy": strategy}


def test_run_evaluation_loop_returns_immediately_when_first_evaluation_passes(session_factory):
    strategy = {
        "strategy_name": "割安株",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return '{"pass": true, "feedback": ""}'

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, session_factory=session_factory)

    assert call_count["n"] == 1
    assert result == {
        "strategy": strategy,
        "iterations": 0,
        "last_feedback": None,
        "next_turn_index": 1,
    }


def test_run_evaluation_loop_refines_and_returns_on_second_pass(session_factory):
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    refined_strategy = {
        "strategy_name": "ゴールデンクロス（改善）",
        "steps": [
            {"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー", "top_n": 50}}
        ],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "対象銘柄数を絞ってください"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, session_factory=session_factory)

    assert result["strategy"] == refined_strategy
    assert result["iterations"] == 1
    assert result["last_feedback"] == "対象銘柄数を絞ってください"
    assert result["next_turn_index"] == 3


def test_run_evaluation_loop_stops_at_max_iterations_when_never_passes(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    refined_once = {
        "strategy_name": "割安株2",
        "steps": [
            {
                "function": "FILTER_BY_FUNDAMENTALS",
                "params": {"conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 10}]},
            }
        ],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(refined_once, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(
        strategy, call_llm=fake_call_llm, max_iterations=2, session_factory=session_factory
    )

    assert result["strategy"] == refined_once
    assert result["iterations"] == 2
    assert result["last_feedback"] == "まだ不十分です"


def test_run_evaluation_loop_rejects_refinement_missing_steps_key(session_factory):
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    # 改善案の応答にstepsキーが無い不正なケース（旧conditions形式が紛れ込む等）。
    invalid_refinement = {"strategy_name": "誤ったスキーマ", "conditions": []}
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(invalid_refinement, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(
        strategy, call_llm=fake_call_llm, max_iterations=2, session_factory=session_factory
    )

    assert result["strategy"] == strategy


def test_run_evaluation_loop_skips_refinement_when_response_is_invalid_json(session_factory):
    strategy = {
        "strategy_name": "割安株",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            "not valid json",
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(
        strategy, call_llm=fake_call_llm, max_iterations=3, session_factory=session_factory
    )

    assert result["strategy"] == strategy
    assert result["iterations"] == 1


def test_run_evaluation_loop_logs_evaluate_and_refine_turns_sharing_one_session(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    refined_strategy = {"strategy_name": "割安株2", "steps": []}
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(
        strategy,
        call_llm=fake_call_llm,
        session_id="dialogue-session-1",
        turn_index_start=5,
        user_id=3,
        session_factory=session_factory,
    )

    assert result["next_turn_index"] == 8

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == "dialogue-session-1"

        generations = session.query(AiGeneration).order_by(AiGeneration.turn_index).all()
        assert [g.feature for g in generations] == [
            "strategy_evaluate",
            "strategy_refine",
            "strategy_evaluate",
        ]
        assert [g.turn_index for g in generations] == [5, 6, 7]
        assert all(g.session_id == "dialogue-session-1" for g in generations)
```

- [ ] **Step 3: テスト実行**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_strategy_builder_evaluation.py -v`
Expected: PASS（全11テスト）

- [ ] **Step 4: 回帰確認**

`run_evaluation_loop`を利用する他モジュールへの影響がないか確認する。

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/ -k "strategy_builder" -v`
Expected: PASS（`test_strategy_builder_pipeline.py`等、`evaluation.py`を直接使わないテストへの影響が無いことを確認）

- [ ] **Step 5: Commit**

```bash
git add strategy_builder/evaluation.py tests/test_strategy_builder_evaluation.py
git commit -m "feat: 戦略評価・改善ループに事実/AI応答のロギングを組み込む"
```

---

## Task 6: AI戦略ビルダー対話タブでのセッションID発行・ロギング

**Files:**
- Modify: `app_tabs/strategy_builder_tab.py`

**Interfaces:**
- Consumes: `common.ai_generation_log.log_ai_generation`（Task 2）、`strategy_builder.evaluation.run_evaluation_loop`（Task 5で`session_id`/`turn_index_start`/`user_id`パラメータ追加済み）

- [ ] **Step 1: インポートを追加**

ファイル先頭のインポート群（5-24行目）に追加:

```python
import uuid

from common.ai_generation_log import log_ai_generation
```

- [ ] **Step 2: セッション状態の初期化を追加**

`render_strategy_builder_tab()`の初期化ブロック（319-331行目）に追加:

```python
    if "strategy_ai_session_id" not in st.session_state:
        st.session_state["strategy_ai_session_id"] = None
    if "strategy_ai_turn" not in st.session_state:
        st.session_state["strategy_ai_turn"] = 0
```

- [ ] **Step 3: 「対話を始める」ボタンで新規セッションを発行**

`_render_idea_input_section()`内のボタン処理（133-138行目）を変更:

```python
    if st.button("対話を始める", disabled=not st.session_state.get("strategy_idea_text")):
        st.session_state["strategy_chat_history"] = [
            {"role": "user", "content": st.session_state["strategy_idea_text"]}
        ]
        st.session_state["strategy_pending_strategy"] = None
        st.session_state["strategy_ai_session_id"] = uuid.uuid4().hex
        st.session_state["strategy_ai_turn"] = 0
        st.rerun()
```

- [ ] **Step 4: 対話ターン・評価改善ループの呼び出しにロギングを組み込む**

`_render_dialogue_section()`内のLLM呼び出しブロック（195-217行目）を変更:

```python
    if history[-1]["role"] == "user" and pending is None:
        sector_jp_values = {
            p["sector_jp"] for p in load_all_company_profiles() if p["sector_jp"]
        }
        sectors = sorted(sector_jp_values)
        prompt = build_dialogue_prompt(history, sectors=sectors)
        with st.spinner("AIが回答を考えています..."):
            raw = call_llm(prompt)
        session_id = st.session_state["strategy_ai_session_id"]
        turn = st.session_state["strategy_ai_turn"]
        log_ai_generation(
            session_id,
            "strategy_dialogue_turn",
            facts={"history": history, "sectors": sectors},
            prompt=prompt,
            ai_output=raw,
            turn_index=turn,
            user_id=get_current_user_id(),
            session_feature="strategy_dialogue",
        )
        st.session_state["strategy_ai_turn"] = turn + 1
        parsed = parse_dialogue_response(raw)
        if parsed["kind"] == "strategy":
            # 確定候補が生成された直後に自動評価・改善ループを1回だけ実行する
            # （Evaluator-Optimizerパターン）。結果を人間の最終確認に回す。
            with st.spinner("戦略条件を評価・改善中..."):
                evaluation_result = run_evaluation_loop(
                    parsed["strategy"],
                    call_llm=call_llm,
                    session_id=session_id,
                    turn_index_start=st.session_state["strategy_ai_turn"],
                    user_id=get_current_user_id(),
                )
            st.session_state["strategy_pending_strategy"] = evaluation_result["strategy"]
            st.session_state["strategy_pending_evaluation"] = evaluation_result
            st.session_state["strategy_ai_turn"] = evaluation_result["next_turn_index"]
        else:
            history.append({"role": "assistant", "content": parsed["text"]})
            st.session_state["strategy_chat_history"] = history
        # ここでst.rerun()せずに関数を抜けると、この後の`if pending is not None:`や
        # チャット入力欄の描画コードが同じ実行内でそのまま続けて動いてしまい、
        # 「AIの返信が追加された直後の画面」を正しい順序で描画し直せない。
        # 明示的にrerunすることで、更新後のhistory/pendingを前提に最初から描画し直す。
        st.rerun()
```

- [ ] **Step 5: 手動確認**

このファイルはプロジェクトの慣習上自動テスト対象外。以下で手動確認する:

Run: `cd ai-stock-investing-tutorial/app && streamlit run app.py`

1. ログインし、「AI戦略ビルダー」タブでテンプレートを選び「対話を始める」を押す
2. 2〜3ターンやり取りし、確定候補が提示される（＝評価・改善ループが動く）ことを確認
3. `data/app.db`を確認（例: `python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('select session_id, turn_index, feature from ai_generations order by id desc limit 10').fetchall())"`）し、同一`session_id`のもとで`strategy_dialogue_turn`・`strategy_evaluate`・（改善が起きれば）`strategy_refine`が連番の`turn_index`で記録されていることを確認
4. 別の投資アイデアで「対話を始める」を再度押し、新しい`session_id`が発行されることを確認

- [ ] **Step 6: Commit**

```bash
git add app_tabs/strategy_builder_tab.py
git commit -m "feat: AI戦略ビルダー対話にセッション単位のロギングを組み込む"
```

---

## Task 7: 管理画面向け一覧取得関数 `admin.list_ai_generations`

**Files:**
- Modify: `admin.py`
- Modify: `tests/test_admin.py`

**Interfaces:**
- Consumes: `db.models.AiGeneration`, `db.models.AiSession`, `db.models.User`（Task 1）
- Produces: `list_ai_generations(limit: int = 200, session_factory=SessionLocal) -> list[dict]`（各dictは`session_id`/`feature`/`ticker`/`username`/`turn_index`/`created_at`/`ai_output`を持つ。`ai_output`は先頭200文字に切り詰め、新しい順）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_admin.py`のインポート（4-6行目）を変更:

```python
from admin import delete_user, list_ai_generations, list_users, set_admin_status
from db.engine import create_db_engine, init_db
from db.models import AiGeneration, AiSession, CompanyProfile, Holding, SectorDisplaySetting, Strategy, User
```

ファイル末尾に追加:

```python
def test_list_ai_generations_returns_recent_rows_with_joined_fields(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

        session.add(
            AiSession(id="s1", feature="stock_detail", ticker="AAA.T", user_id=user_id)
        )
        session.add(
            AiGeneration(
                session_id="s1",
                turn_index=0,
                feature="stock_detail_comment",
                facts="{}",
                prompt="p1",
                ai_output="a" * 250,
            )
        )
        session.commit()

    rows = list_ai_generations(session_factory=session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "s1"
    assert row["feature"] == "stock_detail_comment"
    assert row["ticker"] == "AAA.T"
    assert row["username"] == "taro"
    assert row["turn_index"] == 0
    assert len(row["ai_output"]) == 200


def test_list_ai_generations_returns_newest_first_and_respects_limit(session_factory):
    with session_factory() as session:
        session.add(AiSession(id="s1", feature="stock_detail", ticker="AAA.T"))
        session.add(
            AiGeneration(
                session_id="s1", turn_index=0, feature="stock_detail_comment",
                facts="{}", prompt="p", ai_output="old",
            )
        )
        session.commit()
        session.add(
            AiGeneration(
                session_id="s1", turn_index=1, feature="stock_detail_profile",
                facts="{}", prompt="p", ai_output="new",
            )
        )
        session.commit()

    rows = list_ai_generations(limit=1, session_factory=session_factory)
    assert len(rows) == 1
    assert rows[0]["ai_output"] == "new"


def test_list_ai_generations_handles_missing_user(session_factory):
    with session_factory() as session:
        session.add(AiSession(id="s1", feature="stock_detail", ticker="AAA.T", user_id=None))
        session.add(
            AiGeneration(
                session_id="s1", turn_index=0, feature="stock_detail_comment",
                facts="{}", prompt="p", ai_output="a",
            )
        )
        session.commit()

    rows = list_ai_generations(session_factory=session_factory)
    assert rows[0]["username"] is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_admin.py -v`
Expected: FAIL（`list_ai_generations`が存在しない）

- [ ] **Step 3: `admin.py`に実装を追加**

インポート（8-9行目）を変更:

```python
from db.engine import SessionLocal
from db.models import AiGeneration, AiSession, Holding, SectorDisplaySetting, Strategy, User
```

ファイル末尾に追加:

```python
# admin_tab.pyのAI生成ログ一覧表示から呼ばれる。件数が際限なく増えるテーブルのため、
# 常にlimitで上限を設けて新しい順に返す。
def list_ai_generations(limit: int = 200, session_factory=SessionLocal) -> list[dict]:
    """AI生成ログ（事実・プロンプト・AI応答）を新しい順に返す。ai_outputは
    表示用に長すぎる場合は先頭200文字に切り詰める。"""
    with session_factory() as session:
        rows = (
            session.query(AiGeneration, AiSession, User)
            .join(AiSession, AiGeneration.session_id == AiSession.id)
            .outerjoin(User, AiSession.user_id == User.id)
            .order_by(AiGeneration.created_at.desc(), AiGeneration.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "session_id": generation.session_id,
                "feature": generation.feature,
                "ticker": session_row.ticker,
                "username": user.username if user else None,
                "turn_index": generation.turn_index,
                "created_at": generation.created_at,
                "ai_output": (
                    generation.ai_output[:200]
                    if len(generation.ai_output) > 200
                    else generation.ai_output
                ),
            }
            for generation, session_row, user in rows
        ]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/test_admin.py -v`
Expected: PASS（全7テスト）

- [ ] **Step 5: Commit**

```bash
git add admin.py tests/test_admin.py
git commit -m "feat: 管理画面向けにAI生成ログ一覧取得関数を追加"
```

---

## Task 8: 管理画面へのAI生成ログ一覧表示

**Files:**
- Modify: `app_tabs/admin_tab.py`

**Interfaces:**
- Consumes: `admin.list_ai_generations`（Task 7）

- [ ] **Step 1: インポートを追加**

`app_tabs/admin_tab.py:12`を変更:

```python
from admin import delete_user, list_ai_generations, list_users, set_admin_status
```

- [ ] **Step 2: `render_admin_tab()`に新セクションを追加**

`render_admin_tab()`（32-39行目）を変更:

```python
def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()
    st.divider()
    _render_user_management()
    st.divider()
    _render_market_data_management()
    st.divider()
    _render_ai_generation_log()
```

ファイル末尾に追加:

```python
def _render_ai_generation_log() -> None:
    st.subheader("AI生成ログ（事実・AI見解）")
    generations = list_ai_generations()
    if not generations:
        st.caption("記録されたAI生成はまだありません。")
        return

    display_df = pd.DataFrame(
        [
            {
                "セッションID": g["session_id"],
                "種別": g["feature"],
                "銘柄": g["ticker"] or "―",
                "ユーザー": g["username"] or "―",
                "順番": g["turn_index"],
                "作成日時": g["created_at"],
                "AI応答（先頭200文字）": g["ai_output"],
            }
            for g in generations
        ]
    )
    st.dataframe(display_df, hide_index=True)
```

- [ ] **Step 3: 手動確認**

このファイルはプロジェクトの慣習上自動テスト対象外。以下で手動確認する:

Run: `cd ai-stock-investing-tutorial/app && streamlit run app.py`

1. is_adminユーザーでログインし、「管理者」タブを開く
2. Task 4・Task 6で生成した銘柄詳細コメント・AI戦略ビルダー対話のログが、「AI生成ログ（事実・AI見解）」セクションの表に新しい順で表示されることを確認

- [ ] **Step 4: Commit**

```bash
git add app_tabs/admin_tab.py
git commit -m "feat: 管理画面にAI生成ログの最小限の一覧表示を追加"
```

---

## Task 9: 全体テストスイートの最終確認

**Files:** なし（確認のみ）

- [ ] **Step 1: プロジェクト全体のテストを実行**

Run: `cd ai-stock-investing-tutorial/app && python -m pytest tests/ -v`
Expected: PASS（全テストグリーン。特にTask 1〜7で変更したテストファイルと、`evaluate_strategy`/`run_evaluation_loop`を間接的に使う他のテストファイルに新規の失敗が無いこと）

- [ ] **Step 2: 差分全体を確認**

Run: `cd ai-stock-investing-tutorial/app && git log --oneline -9`
Expected: Task 1〜8の8コミットが確認できる
