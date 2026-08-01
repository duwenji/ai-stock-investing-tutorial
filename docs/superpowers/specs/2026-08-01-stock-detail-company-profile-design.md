# 銘柄詳細ダイアログへの基本情報（業種・市場ポジション・強み）追加

## 背景・課題

現在の銘柄詳細ダイアログ（`app_tabs/shared.py::show_stock_detail_dialog`）は、
株価チャート・PER/PBR/配当利回り・テクニカルシグナル・AI総合分析コメント・
関連ニュースを表示するが、その銘柄がどんな業種でどんな事業を営んでいるか、
市場でのポジションや強みといった基本的な会社情報を含んでいない。

これを追加し、銘柄を初めて見るユーザーでも文脈を掴めるようにする。

## データ取得

`data_api/stock_price_api.py`に新規関数`fetch_company_profile`を追加する。

```python
def fetch_company_profile(ticker_symbol: str) -> dict:
    """指定銘柄の業種・事業内容をyfinance経由で取得する。"""
```

戻り値: `{"ticker": str, "sector": str | None, "industry": str | None, "business_summary": str | None}`。
yfinanceの`Ticker.info`の`sector`/`industry`/`longBusinessSummary`をそのまま使う
（英語表記。既存の17業種分類`SECTOR_MAP`とは統合せず、常にyfinance由来のみを使う）。

`fetch_universe_fundamentals`（228銘柄一括取得）には混ぜない。銘柄詳細を開いた
単一銘柄でのみ呼び出すことで、一括取得のキャッシュに不要なテキストが
含まれるのを避ける。

## プロンプト

既存の`prompt_patterns/stock_detail.py`（銘柄詳細ダイアログ向けプロンプトを
まとめるファイル）に、2つ目の関数として追加する。

```python
def build_company_profile_prompt(
    ticker: str, name: str | None, sector: str | None,
    industry: str | None, business_summary: str | None,
) -> str:
    """事業内容の説明文から、市場でのポジション・強みを日本語で要約させるプロンプトを組み立てる。"""
```

- `business_summary`（yfinanceの英語の事業内容説明）を根拠に、「市場でのポジション・
  強み」を日本語3〜4文で要約するようAIに指示する
- 既存の`build_stock_detail_prompt`と同様、断定的な投資判断は含めない旨を明記する
- `business_summary`が空の場合はこの関数を呼ばず（`generate_stock_detail`側で
  ガードする）、固定の「情報なし」メッセージを使う。無駄なLLM呼び出しを避ける

## `generate_stock_detail`の拡張

`stock_detail/detail.py::generate_stock_detail`に
`fetch_company_profile=default_fetch_company_profile`引数を追加する。

- `fetch_company_profile(ticker)`を呼び、`business_summary`があれば
  `call_llm(build_company_profile_prompt(...))`で`profile_comment`を生成する。
  無ければ`profile_comment`は固定文言（例:「事業内容の情報が取得できませんでした。」）
- payloadに`"profile": {"sector": ..., "industry": ..., "profile_comment": ...}`を追加する
- 既存のキャッシュ形式チェック（`"open" in payload["price_history"]`のときのみ
  キャッシュを再利用）に`"profile" in payload`も条件として加える。これにより、
  この変更より前に作成された旧形式のキャッシュは自動的に再生成される

## UI表示

`app_tabs/shared.py::show_stock_detail_dialog`に「基本情報」セクションを追加する。
配置は銘柄コード・銘柄名の見出し直後、株価チャートの前。

- 業種・詳細業種を`st.write`等で事実として表示する（欠損時は既存の
  PER/PBR等と同じ`"―"`表示に揃える）
- 「AIによる市場ポジション・強みの要約」という見出し付きで`profile_comment`を表示する

既存の「AI総合分析コメント」セクションと同様、事実（yfinance由来の業種・詳細業種）
とAIの考察（市場ポジション・強みの要約）を明確に分けて表示し、
本カテゴリ全体の「事実とAIによる考察を分離する」方針を踏襲する。

## テスト

既存の`tests/test_stock_price_api.py`・`tests/test_stock_detail.py`・
`tests/test_stock_detail_prompt.py`と同じ形式（`FakeTicker`によるモック、
フェイク依存関数の差し替え、キャッシュ往復・旧形式キャッシュからの移行、
ログ出力確認）で追加する。

- `fetch_company_profile`: sector/industry/longBusinessSummaryが揃っている場合と
  欠損している場合の両方をテストする
- `build_company_profile_prompt`: ticker/name/business_summaryが本文に含まれること、
  断定的な投資判断を避ける指示が含まれること
- `generate_stock_detail`: payloadに`profile`が含まれること、
  `business_summary`が空の場合に`call_llm`が呼ばれず固定メッセージになること、
  旧形式（`profile`キーが無い）キャッシュが再生成されること

UIタブ・ダイアログ自体は既存踏襲で自動テスト対象外とする
（`app_tabs/*.py`は現状すべて未テスト）。

## 影響を受けないもの

- 既存の`fetch_fundamentals`/`fetch_universe_fundamentals`（PER/PBR/ROE等の
  一括取得ロジック）
- 既存の`build_stock_detail_prompt`（総合分析コメント生成プロンプト）
- 既存の17業種分類`SECTOR_MAP`・セクターローテーション分析
- 他タブ（スクリーニング・ポートフォリオ・ランキング・AI戦略ビルダー）の
  銘柄詳細ダイアログ呼び出し方法（`show_stock_detail_dialog`のシグネチャは変更しない）
