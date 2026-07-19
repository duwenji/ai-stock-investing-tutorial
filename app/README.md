# stock-advisor-app

[ai-stock-investing-tutorial](../README.md) の教材内容（プロンプト設計・データAPI連携・分析エージェント・ポートフォリオ管理）を統合した、実用のためのStreamlit Webアプリです。

設計の詳細は [docs/superpowers/specs/2026-07-19-portfolio-screening-app-design.md](docs/superpowers/specs/2026-07-19-portfolio-screening-app-design.md) を参照してください。

> ⚠️ 本アプリは教育目的の参考実装であり、投資助言を目的としたものではありません。必ず [DISCLAIMER.md](../DISCLAIMER.md) をお読みください。

## 機能

- **ポートフォリオ**タブ: 保有銘柄（ティッカー・株数・取得単価）を登録し、構成比・損益・リスク（ボラティリティ・相関）・ファンダメンタル・テクニカル・ニュースセンチメントを統合したレビューレポートを生成します。
- **スクリーニング**タブ: 自然言語の条件（例:「PERが15倍以下で配当利回りが3%以上」）を入力すると、主要銘柄（[screening/universe.py](screening/universe.py)、44銘柄）の中から条件に合う銘柄を絞り込みます。AIが解釈した条件は適用前に必ず画面で確認できます。

## 必要な環境

- Python 3.14系（[uv](https://docs.astral.sh/uv/)で管理）
- [Claude Code CLI](https://docs.claude.com/claude-code)（`claude`コマンド）がインストール・ログイン済みであること
  - LLM呼び出しはOpenAI/Anthropic APIキーを使わず、`claude -p`のサブプロセス実行で行います

## セットアップ

```bash
cd app
uv sync
```

## 起動

```bash
uv run streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。

## データの保存場所

- 保有銘柄: `data/holdings.json`
- 日次キャッシュ（ポートフォリオレビュー・ユニバースfundamentals）: `data/cache/`

いずれも `.gitignore` 対象で、実行するたびにローカルへ生成されます。

## テスト

```bash
uv run pytest -v
```

## 構成

```
app.py                      # Streamlitエントリーポイント
data_api/                   # yfinance連携・LLM連携（Claude Code CLI）
prompt_patterns/            # プロンプト生成・スクリーニング条件変換
analysis_agents/            # ファンダメンタル・テクニカル・ニュース分析
portfolio_management/       # 保有銘柄の永続化・構成比/リスク計算・レビュー統合
screening/                  # 固定スクリーニングユニバース
common/                     # 免責事項定数・キャッシュ・JSON解析ヘルパー
tests/                      # pytest（yfinance・Claude Code CLI呼び出しはモック化）
```
