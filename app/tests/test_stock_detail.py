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
