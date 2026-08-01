# 統合ポートフォリオアドバイザーエージェント

## この教材で身につくこと

- 複数の分析エージェント（構成・リスク・ファンダメンタル・テクニカル・ニュース）
  を1つのレポートに統合する設計力
- 集中リスクやセンチメントの偏りを「教育的な観察」として記述する言い回し
- 免責事項をレポート本文の冒頭・末尾の両方に組み込むコード実装

## 概要

これまでの2教材は、それぞれ「単一銘柄の日次情報」「条件検索」という
限定的な用途でした。このツールは、保有銘柄一覧（ティッカー・株数・
取得単価）を入力すると、ポートフォリオ全体を俯瞰する統合レポートを
生成します。

処理の流れは次の4ステップです。

1. 保有銘柄からポートフォリオの構成比・損益を集計する
2. ボラティリティ・相関係数などのリスク指標を計算する
3. 銘柄ごとにファンダメンタル・テクニカル・ニュースのスナップショットを取得する
4. 1〜3の事実データをレポート生成プロンプトに渡し、統合レポートを生成する

生成されるレポートは、あくまで**教育目的の観察事項**であり、
「買うべきか・売るべきか」を指示するものではありません。

## 位置づけ

このツールは、本チュートリアル全体の集大成です。参照する部品は
これまでのほぼ全カテゴリにまたがります。

| ステップ | 参照教材 |
|----------|----------|
| 構成比・損益の集計 | [05-portfolio-management/01](../05-portfolio-management/01-portfolio-analysis-with-ai.md) |
| リスク指標の計算 | [05-portfolio-management/02](../05-portfolio-management/02-risk-assessment.md) |
| ファンダメンタル分析 | [04-analysis-agents/01](../04-analysis-agents/01-fundamental-analysis-agent.md) |
| テクニカル分析 | [04-analysis-agents/02](../04-analysis-agents/02-technical-analysis-agent.md) |
| ニュース分析 | [04-analysis-agents/03](../04-analysis-agents/03-news-research-agent.md) |
| レポート生成 | [02-prompt-patterns/04](../02-prompt-patterns/04-report-generation-prompts.md) |
| LLM呼び出し | [03-data-api/02](../03-data-api/02-llm-api-integration.md) |

01・02で使ったyfinance直接呼び出しの代わりに、
[04-analysis-agents/04-mcp-server-for-stock-data.md](../04-analysis-agents/04-mcp-server-for-stock-data.md)
で構築したMCPサーバー経由でデータ取得する構成に置き換えることも
可能です。演習課題で扱います。

## 主要概念・パラメータ解説

| 要素 | 目的 | 対応する部品 |
|------|------|--------------|
| `holdings: list[dict]` | 保有銘柄一覧（ticker/shares/cost）を表す入力形式 | 本教材で定義 |
| `analyze_portfolio_composition` | 構成比・損益の事実集計 | 05-portfolio-management/01 |
| `assess_risk` | ボラティリティ・相関係数の事実集計 | 05-portfolio-management/02 |
| `build_holding_snapshot` | 銘柄別の事実スナップショットを1つの辞書にまとめる | 本教材で新規実装 |
| `DISCLAIMER_NOTICE` | 免責事項をレポート冒頭・末尾に明示する定数 | 本教材で新規実装 |
| `generate_portfolio_review` | 全ステップを統合し最終レポートを組み立てる | 本教材で新規実装 |

## 実ソースコード（Python / プロンプト例）

### 悪い例

集中リスクや弱いニュースセンチメントの検知結果を、LLMへの指示で
売買行動そのものを示唆する文言にしています。これは投資助言と
誤解されるおそれがあります。

```text
このポートフォリオの中で、今すぐ売却すべき銘柄を1つ挙げてください。
```

### 良い例

観察事項として記述させ、売買の判断や指示は明示的に禁止します。

```text
このポートフォリオの構成比・リスク指標・銘柄別スナップショットを
見て、教育的な観察事項（例: 集中度が高い銘柄、ニュースセンチメント
が弱い銘柄、テクニカルシグナルが弱含みの銘柄）を箇条書きで示して
ください。売買の推奨・指示・目標株価の提示は行わないでください。
```

### オーケストレーション関数

`DISCLAIMER_NOTICE`をレポート文字列の**先頭と末尾の両方**に
明示的に挿入している点に注目してください。

```python
from data_api.llm_client import call_llm                              # 03-data-api/02
from analysis_agents.fundamental_agent import analyze_fundamentals    # 04-analysis-agents/01
from analysis_agents.technical_agent import analyze_technical         # 04-analysis-agents/02
from analysis_agents.news_research_agent import research_news         # 04-analysis-agents/03
from portfolio_management.composition import analyze_portfolio_composition  # 05-pm/01
from portfolio_management.risk import assess_risk                     # 05-portfolio-management/02
from prompt_patterns.report_generation import build_report_prompt     # 02-prompt-patterns/04

DISCLAIMER_NOTICE = (
    "本レポートは教育目的の情報提供であり、投資助言ではありません。"
    "個別銘柄の売買を推奨するものではなく、AIによる考察には誤りが"
    "含まれる可能性があります。投資判断は自己責任で、一次情報の"
    "確認のうえ行ってください。"
)


def build_holding_snapshot(holding: dict) -> dict:
    """保有銘柄1件分の事実データを集約する。

    ファンダメンタル・テクニカル・ニュースの3つの分析エージェントを
    呼び出し、数値と判定結果のみを辞書にまとめる。
    """
    ticker = holding["ticker"]
    fundamentals = analyze_fundamentals(ticker)
    technical = analyze_technical(ticker)
    news = research_news(ticker)
    return {
        "ticker": ticker,
        "shares": holding["shares"],
        "cost": holding["cost"],
        "per": fundamentals.get("per"),
        "pbr": fundamentals.get("pbr"),
        "technical_signal": technical.get("signal"),
        "news_sentiment": news.get("sentiment"),
        "news_confidence": news.get("confidence"),
    }


def generate_portfolio_review(holdings: list[dict]) -> str:
    """保有銘柄一覧から、構成・リスク・銘柄別スナップショットを統合したレポートを生成する。"""
    composition = analyze_portfolio_composition(holdings)
    risk = assess_risk(holdings)
    snapshots = [build_holding_snapshot(h) for h in holdings]

    facts = {"composition": composition, "risk": risk, "holdings": snapshots}
    prompt = build_report_prompt(facts)
    commentary = call_llm(prompt)

    sections = [
        DISCLAIMER_NOTICE,
        "",
        "# ポートフォリオ統合レビュー",
        "",
        commentary,
        "",
        "---",
        "",
        DISCLAIMER_NOTICE,
    ]
    return "\n".join(sections)


if __name__ == "__main__":
    my_holdings = [
        {"ticker": "7203.T", "shares": 100, "cost": 2500},
        {"ticker": "6758.T", "shares": 50, "cost": 12000},
        {"ticker": "9432.T", "shares": 200, "cost": 4000},
    ]
    print(generate_portfolio_review(my_holdings))
```

### 実行結果例

`generate_portfolio_review(my_holdings)`が返すMarkdown文字列の抜粋です。
免責事項が冒頭と末尾の両方に含まれていることを確認してください。

```text
本レポートは教育目的の情報提供であり、投資助言ではありません。
個別銘柄の売買を推奨するものではなく、AIによる考察には誤りが
含まれる可能性があります。投資判断は自己責任で、一次情報の
確認のうえ行ってください。

# ポートフォリオ統合レビュー

### 事実
- 構成比: 7203.T 38% / 6758.T 42% / 9432.T 20%
- ポートフォリオ全体のボラティリティ（年率）: 24.3%
- 7203.Tと6758.Tの相関係数: 0.61

### AIによる考察（教育的な観察事項）
- 6758.Tの構成比が42%と最も高く、値動きへの影響が大きい
  銘柄です。集中度の観点から確認しておく価値があります。
- 9432.Tは直近ニュースセンチメントが中立〜やや弱含みでした。
  一次情報での確認をおすすめします。
- 7203.Tと6758.Tの相関係数が0.61とやや高く、分散効果が
  限定的になっている可能性があります。

---
本レポートは教育目的の情報提供であり、投資助言ではありません。
個別銘柄の売買を推奨するものではなく、AIによる考察には誤りが
含まれる可能性があります。投資判断は自己責任で、一次情報の
確認のうえ行ってください。
```

## 演習課題

これは本チュートリアル全体の最終演習です。これまで学んだ内容を
自由に組み合わせて、このツールを拡張してください。

1. 生成したレポートを、メールまたはSlackへ自動送信する
   ステップを追加してください（APIキーはプレースホルダーで構いません）。
2. データ取得部分を、[04-analysis-agents/04-mcp-server-for-stock-data.md](../04-analysis-agents/04-mcp-server-for-stock-data.md)
   のMCPサーバー経由に置き換えてください。
3. 適時開示情報など、新しいデータソースを1つ追加し、
   `build_holding_snapshot`に組み込んでください。
4. 完成したツールに対して、本教材の「良い例」に沿った
   免責事項・観察事項の言い回しになっているか自己レビューしてください。

## 理解度チェック

- [ ] 複数の分析エージェントの出力を1つのレポートに統合する流れを説明できる
- [ ] 免責事項をレポートの冒頭・末尾の両方に入れる理由を説明できる
- [ ] 「観察事項」として記述することと「売買指示」の違いを説明できる
- [ ] 本チュートリアルで学んだ主要な部品（プロンプト設計・API連携・
      分析エージェント・ポートフォリオ分析）を一通り挙げられる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: スクリーニングダッシュボード](02-screening-dashboard.md) | [次へ: AI戦略ビルダーエージェント →](04-strategy-builder-agent.md)
