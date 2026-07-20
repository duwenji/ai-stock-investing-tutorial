# 銘柄詳細ダイアログ（表クリックで詳細表示） 設計書

## 概要・目的

現状、スクリーニング結果表・一括バックテストのランキング表・ポートフォリオの保有銘柄表は、いずれも銘柄コードの一覧を表示するのみで、個別銘柄の詳細（ファンダメンタルズ・株価チャート・ニュース・AI分析）を見るには別タブへ移動する必要がある。

本機能では、上記3つの表にある銘柄をクリック（またはボタン）することで、その場でモーダルダイアログとして銘柄詳細情報（ファンダメンタルズ・株価チャート・テクニカルシグナル・関連ニュース・AI総合分析コメント）を表示できるようにする。教育目的の参考実装であり、投資助言を行うものではないことをダイアログ内にも明示する（[DISCLAIMER.md](../../../../DISCLAIMER.md) 準拠）。

## スコープ

- v1で実装する:
  - スクリーニングタブの結果表・一括バックテストタブのランキング表: 行クリックで銘柄詳細ダイアログを表示
  - ポートフォリオタブの保有銘柄一覧: 行ごとに「詳細」ボタンを設置し、クリックで同ダイアログを表示
  - 銘柄詳細ダイアログの内容: 銘柄コード・銘柄名、株価チャート（6ヶ月）、ファンダメンタルズ（PER・PBR・配当利回り）、テクニカルシグナル、関連ニュース（リンク付き）、AI総合分析コメント
  - 銘柄単位・日次のキャッシュ（既存 `common/cache.py` の方式を踏襲）
- v1で実装しない（将来課題）:
  - バックテストタブ（単一銘柄比較表）への適用（銘柄が1つしかないため対象外）
  - ダイアログ内でのポートフォリオへの追加・削除などの操作
  - 複数銘柄の詳細比較ビュー

## 技術的制約

インストール済みStreamlit（1.59.2）では `st.dataframe` は `on_select`（行クリック選択）に対応しているが、`st.data_editor` は対応していない。ポートフォリオタブの保有銘柄表は株数・取得単価のインライン編集に `st.data_editor` を使っているため、この表だけは行クリックではなく「詳細」ボタン方式（`st.columns` で行ごとに自前描画）とする。既存の `st.data_editor` によるインライン編集機能はそのまま維持する。

## モジュール構成

既存パターン（プロンプト生成は `prompt_patterns/`、データ取得・分析の統合は機能別ディレクトリ）を踏襲する。

```
app/
  prompt_patterns/
    stock_detail.py
      build_stock_detail_prompt(ticker, name, fundamentals, technical, news) -> str   # 新規
  stock_detail/
    __init__.py                                                                        # 新規
    detail.py
      generate_stock_detail(ticker, name, cache_dir, call_llm=default_call_llm, ...) -> dict  # 新規
  app.py
    show_stock_detail_dialog(ticker, name)          # 新規：@st.dialog
    _handle_table_selection(state_key, event, df)   # 新規：行選択共通ヘルパー
    「スクリーニング」タブ                            # session_state化・行選択対応
    「一括バックテスト」タブ                          # session_state化・行選択対応
    「ポートフォリオ」タブ                            # 詳細ボタン行を追加
  tests/
    test_stock_detail_prompt.py                     # 新規
    test_stock_detail.py                             # 新規
```

## コアロジック

### `prompt_patterns/stock_detail.py`

```python
def build_stock_detail_prompt(
    ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]
) -> str:
```

- 既存の `build_comment_prompt`（`prompt_patterns/screening.py`）・`build_backtest_prompt` と同じ調子でプロンプトを組み立てる
- 銘柄コード・銘柄名（あれば）、PER・PBR・配当利回り、テクニカルシグナル、直近ニュース見出し（`- {title}` の箇条書き、0件時は `- (ニュースなし)`）を埋め込む
- 「投資家向けの総合分析コメントを日本語で3〜4文程度で作成してください。断定的な売買判断は含めないでください。」という指示文を含める
- 出力はプレーンテキスト（JSON化不要、コメント文そのものを `call_llm` の返り値としてそのまま使う）

### `stock_detail/detail.py`

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
) -> dict:
```

- キャッシュキー: `f"stock-detail-{ticker}"`（`common/cache.py` の日次キャッシュ。銘柄コードのみでよく、ハッシュ化は不要）
- キャッシュヒット時: `json.loads` して返す（API・LLM呼び出しなし）
- キャッシュミス時:
  1. `history = fetch_price_history(ticker, period="6mo")`
  2. `fundamentals = analyze_fundamentals(ticker)`
  3. `technical = analyze_technical(history)`（`fetch_price_history` は取得失敗時も `Close` 列を含む空DataFrameを返すため、`analyze_technical` は既存ロジックのまま `{"ma_short": None, "ma_long": None, "signal": "データ不足"}` を返す。既存の `app.py`（ポートフォリオタブ）も同様に空データを無条件で渡しており、追加のガードは不要）
  4. `news = fetch_news(ticker)`
  5. `prompt = build_stock_detail_prompt(ticker, name, fundamentals, technical, news)` → `comment = call_llm(prompt)`
  6. 返り値を組み立ててキャッシュに書き込み、返す
- 返り値（JSON化可能な形。株価は日付・終値のリストに変換）:

```python
{
    "ticker": ticker,
    "name": name,
    "price_history": {"dates": list[str], "close": list[float]},  # 空の場合は両方 []
    "fundamentals": {"per": ..., "pbr": ..., "dividend_yield": ...},
    "technical": {"ma_short": ..., "ma_long": ..., "signal": ...},
    "news": [{"title": ..., "publisher": ..., "link": ...}, ...],
    "comment": "AI総合分析コメント文字列",
}
```

## UI設計 — `app.py`

### `show_stock_detail_dialog(ticker, name)`（新規・共通コンポーネント）

```python
@st.dialog("銘柄詳細情報", width="large")
def show_stock_detail_dialog(ticker: str, name: str | None):
    with st.spinner("銘柄情報を取得中..."):
        detail = generate_stock_detail(ticker, name, CACHE_DIR, call_llm=call_llm)

    st.subheader(f"{ticker} {detail.get('name') or ''}")

    price_history = detail["price_history"]
    if price_history["dates"]:
        chart_df = pd.DataFrame(
            {"Close": price_history["close"]},
            index=pd.to_datetime(price_history["dates"]),
        )
        st.line_chart(chart_df)
    else:
        st.info("株価データを取得できませんでした。")

    fundamentals = detail["fundamentals"]
    col1, col2, col3 = st.columns(3)
    col1.metric("PER", fundamentals.get("per") if fundamentals.get("per") is not None else "―")
    col2.metric("PBR", fundamentals.get("pbr") if fundamentals.get("pbr") is not None else "―")
    col3.metric(
        "配当利回り(%)",
        fundamentals.get("dividend_yield") if fundamentals.get("dividend_yield") is not None else "―",
    )

    st.write(f"テクニカルシグナル: **{detail['technical'].get('signal')}**")

    st.subheader("AI総合分析コメント")
    st.write(detail["comment"])

    st.subheader("関連ニュース")
    news_items = detail["news"]
    if not news_items:
        st.write("ニュースが取得できませんでした。")
    for item in news_items:
        title = item.get("title") or "(タイトルなし)"
        publisher = item.get("publisher") or "?"
        link = item.get("link")
        if link:
            st.markdown(f"- [{title}]({link})（{publisher}）")
        else:
            st.markdown(f"- {title}（{publisher}）")

    st.markdown(DISCLAIMER_NOTICE)
```

### `_handle_table_selection(state_key, event, df)`（新規・共通ヘルパー）

```python
def _handle_table_selection(state_key: str, event, df: pd.DataFrame):
    current = event.selection.rows[0] if event.selection.rows else None
    if current != st.session_state.get(state_key):
        st.session_state[state_key] = current
        if current is not None:
            row = df.iloc[current]
            show_stock_detail_dialog(row["ticker"], row.get("name") or "")
```

`st.dataframe(..., on_select="rerun")` は行選択のたびにアプリ全体をリランする。選択インデックスは選択が変わらない限りリラン後も保持されるため、「前回と選択行が変わった時だけダイアログを開く」ことで、ダイアログを閉じた後の無関係なリランで再度開いてしまう問題を防ぐ。同じ行を再度開くには、一度選択解除（同じ行を再クリック）してから再度クリックする必要がある（`selection_mode="single-row"` の標準的なトグル挙動）。

### スクリーニングタブの変更

現状、AI条件解釈（`call_llm`）は `condition_text` が空でない限り毎リラン時に再実行され、絞り込み結果の計算・表示は「この条件で絞り込む」ボタンクリック時のみの分岐内にある。行選択によるリランでも結果表示を維持し、かつLLM呼び出しの増加を避けるため、以下のように変更する。

1. 条件解釈のキャッシュ化: `st.session_state["screening_condition_text"]` に前回の `condition_text` を保持し、変化がなければ `call_llm` を再実行せず `st.session_state["screening_filters"]` を再利用する
2. 絞り込み結果の永続化: 「この条件で絞り込む」ボタンクリック時に `result_df` と `comments` を計算し、`st.session_state["screening_result_df"]` / `st.session_state["screening_comments"]` に保存する
3. 表示部分をボタン分岐の外に出し、`st.session_state["screening_result_df"]` が存在する限り常に表示する
4. `st.dataframe` に `on_select="rerun"`, `selection_mode="single-row"`, `key="screening_result_table"` を追加し、`_handle_table_selection("screening_selected_row", event, result_df)` を呼ぶ

### 一括バックテストタブの変更

現状と同様の理由で、`payload` を `st.session_state["ranking_payload"]` に保存し、ボタン分岐の外側で「保存済みの `payload` があれば常に表示」する形に変更する。表示用の `ranking_df` 生成・`st.dataframe` 呼び出しもボタン分岐の外に移動し、`on_select="rerun"`, `selection_mode="single-row"`, `key="ranking_table"` を追加、`_handle_table_selection("ranking_selected_row", event, ranking_df)` を呼ぶ。

### ポートフォリオタブの変更

`st.data_editor` によるインライン編集はそのまま維持する。保存後の `holdings` を使い、保存ボタン処理の後に以下を追加する。

```python
if holdings:
    st.subheader("銘柄詳細を見る")
    for holding in holdings:
        ticker = holding["ticker"]
        name = candidate_names.get(ticker, "")
        col_ticker, col_name, col_button = st.columns([2, 4, 2])
        col_ticker.write(ticker)
        col_name.write(name)
        if col_button.button("詳細", key=f"portfolio_detail_{ticker}"):
            show_stock_detail_dialog(ticker, name)
```

## エラーハンドリング

- 株価取得失敗・空データ: チャート部分のみ「株価データを取得できませんでした。」に差し替え、他の情報は表示を継続
- ニュース0件: 「ニュースが取得できませんでした。」を表示
- AIコメント生成失敗（`call_llm` が例外を投げる、または空文字を返す）: 既存の `generate_backtest_explanation` 等と同様、`call_llm` 呼び出し自体は例外を上位に伝播させる既存方針を踏襲する（アプリ全体で個別に try/except していないため、本機能でも新たな例外処理は追加しない）
- ダイアログを開いた状態でAPI呼び出しが数秒かかることを `st.spinner` でユーザーに示す

## テスト方針

- `tests/test_stock_detail_prompt.py`: `build_stock_detail_prompt` が銘柄コード・銘柄名・ファンダメンタルズ・テクニカルシグナル・ニュース見出しをプロンプトに含めること、ニュース0件時に `(ニュースなし)` を含めることを検証
- `tests/test_stock_detail.py`:
  - `generate_stock_detail` がキャッシュミス時にフェイクの `fetch_price_history`/`fetch_news`/`analyze_fundamentals`/`analyze_technical`/`call_llm` を正しい引数で呼び出し、期待した形の辞書を返すこと
  - キャッシュヒット時に上記の依存関数を一切呼び出さず、キャッシュ済みの内容をそのまま返すこと（`tmp_path` をキャッシュディレクトリとして使用）
  - 株価データが空の場合に `price_history` が `{"dates": [], "close": []}` になること
- `app.py` のUI部分（ダイアログ表示・行選択ハンドリング・タブごとの結果表示）は既存方針（README「テスト」節）通り自動テスト対象外とし、`uv run python -m streamlit run app.py` を起動して以下を手動確認する:
  - スクリーニングタブ: 絞り込み実行後、結果表の行をクリックしてダイアログが開くこと、閉じた後に無関係な操作で再度開かないこと
  - 一括バックテストタブ: 実行後、ランキング表の行をクリックしてダイアログが開くこと
  - ポートフォリオタブ: 保有銘柄保存後、各行の「詳細」ボタンでダイアログが開くこと、`st.data_editor` の株数・取得単価編集が引き続き機能すること

## ドキュメント更新

- `README.md` の「機能」各タブの説明に、銘柄詳細ダイアログ表示に対応した旨を追記する

## v1スコープ外（将来課題）

- バックテストタブへの適用
- ダイアログ内でのポートフォリオ操作（追加・削除）
- 複数銘柄の詳細比較ビュー
