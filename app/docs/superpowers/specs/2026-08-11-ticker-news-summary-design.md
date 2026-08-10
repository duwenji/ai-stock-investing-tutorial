# ticker_news 本文（summary）保存・活用 設計

## 背景・目的

`ticker_news` テーブル（`db/models.py` の `TickerNews`）は現在 `title`/`publisher`/`link`/`fetched_at` のみを保持し、見出しだけを蓄積している。AI総合コメント（`prompt_patterns/stock_detail.py`）やQ&Aタブのニュース回答（`prompt_patterns/qa_routing.py`）も見出し一覧のみを根拠にLLMへ渡している。

yfinance の実レスポンスを確認したところ、`ticker.news` の各記事の `content.summary` に本文の要約テキスト（英文、数十〜2000文字程度）が実際に含まれている。これを `ticker_news` に保存し、AIコメント・Q&A回答・画面表示の3箇所で活用することで、見出しだけより根拠のある分析・回答を生成できるようにする。

## スコープ外

- リンク先ページの全文スクレイピング（サイトごとにHTML構造が異なり壊れやすく、著作権・利用規約上のリスクもあるため見送る）。
- 既存に蓄積済みの `ticker_news` 行への `summary` バックフィル（`_insert_new_ticker_news` は既知の記事を重複判定でスキップするため、既存行は再取得されない。今後の新規記事から自然に蓄積される想定で、遡及的なバックフィルは行わない）。
- `summary` のトリミング（AIプロンプトへは全文そのまま含める。ユーザー確認済み）。
- `summary` のDB保存時・AIプロンプト投入時の翻訳（英語のまま保存・利用する。LLMは英語入力を読んで日本語で出力できるため、AIコメント/Q&A回答の生成には翻訳不要。翻訳が必要なのは人が読む画面表示のみで、D節で対応する）。

## A. DBスキーマ

### 現状

`TickerNews` は `id`/`ticker`/`title`/`publisher`/`link`/`fetched_at` のみ。プロジェクトはAlembic等を使わず、`db/engine.py` の `init_db()` 内で `Base.metadata.create_all()` 後に、既存DBへの列追加を `_add_column_if_missing()` ヘルパー経由のALTER TABLEで個別に吸収する方針（例: `_ensure_company_profile_sector_jp_column`）。

### 変更内容

`db/models.py` の `TickerNews` に `summary: Mapped[str | None] = mapped_column(Text, nullable=True)` を追加する。

`db/engine.py` に `_ensure_ticker_news_summary_column(engine)` を追加し、`_ensure_company_profile_sector_jp_column` と同型の実装（`PRAGMA table_info(ticker_news)` で既存列を確認し、無ければ `_add_column_if_missing(connection, "ticker_news", existing_columns, "summary", "TEXT")`）とする。`init_db()` から呼び出す（`_ensure_company_profile_sector_jp_column(engine)` の呼び出し直後に追加）。

### テスト

- `test_db_engine.py` に、`summary` 列を持たない旧スキーマの `ticker_news` テーブルを用意した状態で `init_db()` を呼び、`summary` 列が追加されることを検証するテストを追加する（既存の `sector_jp` 列追加テストと同様の形）。

## B. データ取得

### 現状

`data_api/stock_price_api.py` の `_fetch_news_from_yfinance` は `content` から `title`/`publisher`（`provider.displayName`）/`link` のみを抽出する。`_insert_new_ticker_news` はこれらのみで `TickerNews` を作成し、`fetch_news` の戻り値dictも同3項目のみ。

### 変更内容

`_fetch_news_from_yfinance` で `content.get("summary")` を取得し、戻り値の各itemに `"summary"` を追加する。

`_insert_new_ticker_news` で `TickerNews(..., summary=item.get("summary"))` として保存する（既存の重複判定ロジック＝`link` があれば `(ticker, link)`、無ければ `(ticker, title, publisher)` は変更しない。`summary` は判定キーに含めない）。

`fetch_news` の戻り値dict（`{"title": ..., "publisher": ..., "link": ...}`）に `"summary": row.summary` を追加する。

### テスト

- `tests/test_stock_price_api.py` の `FakeTicker`/`MissingNewsFieldsTicker` のニュースfixtureに `summary` を含む記事・含まない記事の両方を用意し、`test_fetch_news_returns_title_publisher_and_link`（アサーション対象に`summary`を追加、テスト名も実態に合わせて更新）や `test_fetch_news_handles_missing_nested_fields` で `summary` が正しく格納・返却される（無い場合は `None`）ことを検証する。
- 既存の重複排除系テスト（`test_fetch_news_accumulates_across_calls_without_duplicates` 等）は `summary` の有無に関わらず動作することを確認する（ロジック変更なしなので回帰確認のみ）。

## C. プロンプトへの活用

### 現状

- `build_stock_detail_prompt`（`prompt_patterns/stock_detail.py`）: `news_titles = "\n".join(f"- {item.get('title')}" for item in news)` で見出しのみを列挙。
- `build_news_answer_prompt`（`prompt_patterns/qa_routing.py`）: `lines = "\n".join(f"- {item['title']}" for item in news)` で見出しのみを列挙。

### 変更内容

両関数とも、`summary` がある記事は見出しの下に要約を付記する形式に変更する。

```
- {title}
  要約: {summary}
```

`summary` が `None`/空文字の記事は要約行を省略し、見出しのみ（`- {title}`）とする。ニュースが1件も無い場合の代替文言（`- (ニュースなし)`）はそのまま維持する。長さの制限は行わず、`summary` を全文そのまま含める（ユーザー確認済み）。

### テスト

- `tests/test_stock_detail_prompt.py`: `summary` を含むニュースitemを渡した場合にプロンプト文字列に要約行が含まれること、`summary` が `None` の場合はその記事の要約行が出力されないことを検証するテストを追加する。
- `tests/test_qa_routing.py`: 同様に `build_news_answer_prompt` について要約行の有無を検証するテストを追加する。

## D. 要約の日本語訳（画面表示専用）

### 現状

`summary` は英文のまま。AIコメント/Q&A回答用プロンプト（C節）はLLMが英語を読んで日本語で出力するため翻訳不要だが、画面に英文のまま表示するのはユーザーにとって読みにくい。既存コードには類似パターンとして、`stock_detail/detail.py` の `generate_stock_detail` が `company_profile.get("business_summary")`（英文）を `build_company_profile_prompt` 経由で `call_llm` に渡し、日本語の講評コメント（`profile_comment`）を生成してキャッシュ済みペイロードに含めている例がある。

### 変更内容

`prompt_patterns/stock_detail.py` に `build_news_summary_translation_prompt(summaries: list[str]) -> str` を追加する。複数の英文要約を渡し、「各要約を日本語に翻訳し、区切り文字 `@@@` を1行だけ挟んで、入力と同じ順序・同じ件数で出力してください（翻訳文以外は出力しないこと）」という指示のプロンプトを組み立てる。

`stock_detail/detail.py` の `generate_stock_detail` で、`news = fetch_news(ticker)` の後に以下を行う:

1. `news` のうち `summary` がある記事だけを抜き出し、その `summary` のリストを作る。1件も無ければ以降のLLM呼び出しはスキップする。
2. `build_news_summary_translation_prompt` でプロンプトを組み立て、`call_llm` を1回呼ぶ（既存の `comment`/`profile_comment` 生成と同様、`generate_stock_detail` 全体の結果がキャッシュされるため、キャッシュヒット時はこの呼び出しも再実行されない）。
3. 応答を `@@@` で分割し、件数が入力件数と一致する場合のみ、元の記事の順序に対応させて各記事に `summary_ja` を追加する。件数が一致しない場合（LLMが指示通りの件数を返さなかった場合）は `summary_ja` を追加せず、警告ログを出す（画面表示側は `summary_ja` が無ければ英文 `summary` にフォールバックする。E節参照）。

### テスト

- `tests/test_stock_detail_prompt.py`: `build_news_summary_translation_prompt` が要約リストと `@@@` 区切りの指示を含むプロンプトを生成することを検証する。
- `tests/test_stock_detail.py`: `call_llm` をモックし、(a) `summary` を持つ記事がある場合に翻訳用の `call_llm` 呼び出しが行われ、応答が `@@@` で正しく分割されて各記事の `summary_ja` に反映されること、(b) `summary` を持つ記事が1件も無い場合は翻訳用の `call_llm` 呼び出しが行われないこと、(c) 応答の分割件数が入力件数と一致しない場合は `summary_ja` が設定されず処理が落ちないこと、を検証する。

## E. 画面表示

### 現状

`app_tabs/shared.py` の「関連ニュース」一覧（`render_stock_detail` 内、`st.subheader("関連ニュース")` 以降）は、記事ごとに `- [title](link)（publisher）` または `- title（publisher）` を `st.markdown` で1行表示するのみ。

### 変更内容

各記事の見出し行はそのまま維持し、`item.get("summary_ja") or item.get("summary")` が取得できる場合は `st.expander("要約を見る")` を見出し行の下に追加し、展開すると（優先順位: 日本語訳 > 英文原文）その本文を表示する。どちらも無い記事は現状通り見出し行のみ。

### テスト

Streamlit UIの描画部分（`shared.py` の `render_stock_detail`）は既存コードベースでもユニットテスト対象外のため、本設計でも自動テストは追加しない。実装後に手動確認する。
