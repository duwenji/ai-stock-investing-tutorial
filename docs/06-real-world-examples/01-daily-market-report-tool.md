# 日次マーケットレポート自動生成ツール

## この教材で身につくこと

- 価格・財務データ取得とニュース分析を1つのCLIツールに統合する設計力
- 「事実」と「AIによる考察」を分離したレポートを複数銘柄分まとめる方法
- 同日の再実行でAPI呼び出しコストを無駄にしないキャッシュ設計

## 概要

このツールは、ウォッチリスト銘柄（例: 保有銘柄・監視銘柄のティッカー一覧）を
入力すると、朝の情報収集を代行するMarkdownレポートを1本出力するCLIです。

処理の流れは次の3ステップです。

1. `yfinance` で各銘柄の株価・財務データを取得する
2. 直近ニュースのセンチメントを集約する
3. 銘柄ごとの事実データをレポート生成プロンプトに渡し、LLMに解説文を書かせる

これまでの教材で作った部品を**呼び出す側**のコードだけを示します。
各部品の実装は参照リンク先の教材を確認してください。

## 位置づけ

このツールは、03-data-apiと02-prompt-patternsの組み合わせを
「複数銘柄・毎日実行」というユースケースに拡張したものです。

- 株価・財務データ取得: [03-data-api/01-stock-price-api.md](../03-data-api/01-stock-price-api.md)
- LLM API呼び出し: [03-data-api/02-llm-api-integration.md](../03-data-api/02-llm-api-integration.md)
- ニュース分析エージェント: [04-analysis-agents/03-news-research-agent.md](../04-analysis-agents/03-news-research-agent.md)
- ファンダメンタル分析エージェント: [04-analysis-agents/01-fundamental-analysis-agent.md](../04-analysis-agents/01-fundamental-analysis-agent.md)
- レポート生成プロンプト: [02-prompt-patterns/04-report-generation-prompts.md](../02-prompt-patterns/04-report-generation-prompts.md)

02-screening-dashboard.mdでは同じ部品を「ユーザー入力起点のUI」として
再構成します。03-portfolio-advisor-agent.mdでは、このレポートに
ポートフォリオ視点（保有比率・リスク）を加えてさらに統合します。

## 主要概念・パラメータ解説

| 要素 | 目的 | 対応する部品 |
|------|------|--------------|
| `collect_facts(ticker)` | 銘柄ごとの事実データ（数値）のみを集約する | yfinance / ファンダメンタル分析エージェント / ニュース分析 |
| `build_report_prompt(facts)` | 事実データをレポート生成プロンプトへ埋め込む | 02-prompt-patterns/04（事実/考察分離・免責事項自動付与） |
| `call_llm(prompt)` | LLMに解説文を生成させる | 03-data-api/02 |
| `generate_daily_report(tickers)` | 全銘柄分の結果を1本のMarkdownに結合する | 本教材で新規実装 |
| 日付キー付きキャッシュ | 同日再実行時の無駄なAPI呼び出しを防ぐ | 本教材で新規実装 |

## 実ソースコード（Python / プロンプト例）

### オーケストレーション関数

各行の右のコメントに、実装を参照すべき教材を示しています。
このファイル自体は関数を**インポートして使う側**のコードです。

```python
import datetime
import sys

from data_api.stock_price_api import fetch_price_history       # 03-data-api/01
from data_api.llm_client import call_llm                         # 03-data-api/02
from analysis_agents.fundamental_agent import analyze_fundamentals  # 04-analysis-agents/01
from analysis_agents.news_research_agent import research_news    # 04-analysis-agents/03
from prompt_patterns.report_generation import build_report_prompt  # 02-prompt-patterns/04


def collect_facts(ticker: str) -> dict:
    """事実（Python側で取得・計算した数値）のみを集約する。

    LLMにはこの辞書だけを渡し、数値の再計算はさせない。
    """
    price_df = fetch_price_history(ticker, period="5d")
    fundamentals = analyze_fundamentals(ticker)
    news = research_news(ticker)

    latest_close = float(price_df["Close"].iloc[-1])
    prev_close = float(price_df["Close"].iloc[-2])
    change_pct = round((latest_close - prev_close) / prev_close * 100, 2)

    return {
        "ticker": ticker,
        "latest_close": latest_close,
        "change_pct": change_pct,
        "per": fundamentals.get("per"),
        "pbr": fundamentals.get("pbr"),
        "news_sentiment": news.get("sentiment"),
        "news_confidence": news.get("confidence"),
    }


def generate_daily_report(tickers: list[str]) -> str:
    """ウォッチリスト銘柄の日次マーケットレポートをMarkdownで生成する。"""
    sections = []
    for ticker in tickers:
        facts = collect_facts(ticker)
        # build_report_prompt は事実/考察の分離と免責事項の付与を内包する
        prompt = build_report_prompt(facts)
        commentary = call_llm(prompt)
        sections.append(commentary)

    today = datetime.date.today().isoformat()
    header = f"# 日次マーケットレポート（{today}）\n\n"
    return header + "\n\n---\n\n".join(sections)


if __name__ == "__main__":
    watchlist = sys.argv[1:] or ["7203.T", "6758.T", "9432.T"]
    report = generate_daily_report(watchlist)
    print(report)
```

コマンドライン実行例です。

```bash
python daily_report.py 7203.T 6758.T 9432.T
```

### 悪い例

再実行のたびに全銘柄の価格取得・ニュース収集・LLM呼び出しを
やり直しています。同じ日に何度実行しても結果はほぼ同じなのに、
API利用料と待ち時間だけが増えます。

```python
# 悪い例: 毎回フルで再取得・再生成する
if __name__ == "__main__":
    watchlist = sys.argv[1:] or ["7203.T", "6758.T", "9432.T"]
    print(generate_daily_report(watchlist))  # 実行するたびにLLMを呼び出す
```

### 良い例

生成済みレポートを日付をキーにローカルファイルへキャッシュします。
同日中の再実行はキャッシュを返すだけになり、コストを節約できます。

```python
from pathlib import Path

CACHE_DIR = Path("cache/daily_reports")


def generate_daily_report_cached(tickers: list[str]) -> str:
    """当日分のキャッシュがあれば再利用し、なければ生成して保存する。"""
    today = datetime.date.today().isoformat()
    cache_path = CACHE_DIR / f"{today}.md"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    report = generate_daily_report(tickers)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    watchlist = sys.argv[1:] or ["7203.T", "6758.T", "9432.T"]
    print(generate_daily_report_cached(watchlist))
```

銘柄構成やウォッチリストを変更した場合は、キャッシュキーに
ウォッチリストの内容も含めるなどの拡張を検討してください。

### 実行結果例

`generate_daily_report(["7203.T"])` が返すMarkdown文字列の抜粋です。

```text
# 日次マーケットレポート（2026-07-19）

## 7203.T（トヨタ自動車）

### 事実
- 終値: 2,850円（前日比 +1.24%）
- PER: 10.2倍 / PBR: 1.1倍
- ニュースセンチメント: ポジティブ（確信度 0.68）

### AIによる考察
直近の株価上昇は、前日ニュースで報じられた増産計画が
好感された可能性があります。PERは同業他社と比較して
低水準であり、割安感が意識されているとも考えられます。
ただし本考察は事実データに基づく仮説であり、投資判断の
根拠として単独で使用しないでください。

---
本レポートはAIによる教育目的の情報提供です。投資助言では
ありません。投資判断は自己責任で、一次情報の確認のうえ
行ってください。
```

## 演習課題

1. `collect_facts` にテクニカル指標（[04-analysis-agents/02](../04-analysis-agents/02-technical-analysis-agent.md)）
   を追加し、レポートに含めてください。
2. ウォッチリストが10銘柄を超える場合、LLM呼び出しを並列化する
   方法を検討してください（レート制限に注意）。
3. `generate_daily_report_cached` に、当日のニュースが更新された
   場合だけ再生成する仕組みを追加してください。

## 理解度チェック

- [ ] 事実データとAIによる考察を分離してレポート化する理由を説明できる
- [ ] 同日再実行時にキャッシュを使う設計のメリットを説明できる
- [ ] 各処理ステップがどの教材の部品に対応するか説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 06-real-world-examples](00-README.md) | [次へ: スクリーニングダッシュボード →](02-screening-dashboard.md)
