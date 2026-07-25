# スクリーニング 業種フィルタ対応 設計書

## 概要・目的

スクリーニングタブ（`app.py`の`tab_screening`）は、自然言語で入力した条件をLLMがJSON形式のフィルタ（`field`/`operator`/`value`）に変換し、`prompt_patterns/screening.apply_filters()`でユニバース銘柄を絞り込む仕組みになっている。現状LLMに許可しているfieldは`per`（PER）・`pbr`（PBR）・`dividend_yield_pct`（配当利回り）の3つのみで、業種による絞り込みができない。

一方、セクターローテーションタブ用に`screening/sectors.py`の`SECTOR_MAP`（銘柄コード→東証17業種区分）が既に存在する。これを流用し、スクリーニングの自然言語条件でも「自動車株」「銀行セクターで」のような業種名を使った絞り込みができるようにする。

## スコープ

- v1で実装する:
  - スクリーニング用ユニバースDataFrameに`sector`列を追加（`SECTOR_MAP`から導出）
  - `build_screening_prompt()`に有効な業種名一覧を渡し、LLMが自由記述の業種表現を正確な業種名にマッピングして`sector`フィールドのフィルタを出力できるようにする
  - 絞り込み結果の一覧表に「業種」列を表示
  - 上記変更に対応するユニットテストの追加
- v1で実装しない（将来課題）:
  - 業種専用のドロップダウン/マルチセレクトUI（今回はブレインストーミングで自然言語条件への統合を採用したため対象外）
  - 業種の部分一致・複数業種のOR指定（`apply_filters`は単一値の等号のみ）

## 実装設計

### 1. `screening/sectors.py`（変更なし、参照のみ）

既存の`SECTOR_MAP: dict[str, str]`をそのまま使う。

### 2. `data_api/stock_price_api.py`（変更なし）

`fetch_universe_fundamentals`はticker/name/per/pbr/dividend_yield_pct/market_capのみを返す設計を維持する。業種はユニバース固定の静的マッピングであり銘柄ごとのAPI取得結果ではないため、マージは呼び出し側（`app.py`）で行う。

### 3. `prompt_patterns/screening.py`

`build_screening_prompt()`に業種一覧を受け取る引数を追加する。

```python
def build_screening_prompt(condition_text: str, sectors: list[str] | None = None) -> str:
    # 自由記述の条件文をLLMに解釈させ、Python側で扱える構造化フィルタへ変換させる。
    # 使用可能なfieldを限定することで、存在しない列や不正な条件の生成を防ぐ。
    sector_line = ""
    if sectors:
        sector_list = "、".join(sectors)
        sector_line = (
            "sector（業種）を使う場合、valueは次の業種名のいずれか一つを"
            f"そのまま正確に使ってください（表記ゆれを吸収し、最も近いものを選ぶこと）: {sector_list}\n"
        )
    return (
        "次の投資条件をJSON形式のフィルタ配列に変換してください。\n"
        "使用できるfieldは per（PER）、pbr（PBR）、dividend_yield_pct"
        "（配当利回り、単位はパーセントの数値。例: 3%なら3）、sector（業種）のいずれかです。\n"
        f"{sector_line}"
        "sectorのoperatorは\"==\"のみ使用してください。\n"
        '出力形式: [{"field": "per", "operator": "<=", "value": 15}] の'
        "ようなJSON配列のみを出力してください。説明文やコードブロック記法は不要です。\n\n"
        f"条件: {condition_text}"
    )
```

`apply_filters()`・`build_comment_prompt()`・`generate_screening_comments()`は変更不要。`apply_filters`は既にfieldのホワイトリスト方式で汎用的に動作し（`operator.eq`は文字列比較にも使える）、`build_comment_prompt`は既に`sector`列があれば含める実装になっている。

### 4. `app.py`（`tab_screening`）

`SECTOR_MAP`は既にimport済み（`from screening.sectors import SECTOR_MAP`、セクタータブで使用中）なのでそのまま使う。

```python
if st.session_state.get("screening_condition_text") != condition_text:
    prompt = build_screening_prompt(condition_text, sectors=sorted(set(SECTOR_MAP.values())))
    ...
```

絞り込み実行部分で`sector`列を追加する:

```python
if st.button("この条件で絞り込む"):
    universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
    universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
        universe_df["name"]
    )
    universe_df["sector"] = universe_df["ticker"].map(SECTOR_MAP)
    result_df = apply_filters(universe_df, filters)
    ...
```

結果表の`column_config`に業種列を追加する:

```python
event = st.dataframe(
    result_df,
    column_config={
        "ticker": st.column_config.TextColumn("銘柄コード"),
        "name": st.column_config.TextColumn("銘柄名"),
        "sector": st.column_config.TextColumn("業種"),
        "per": st.column_config.NumberColumn("PER"),
        "pbr": st.column_config.NumberColumn("PBR"),
        "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
        "market_cap": st.column_config.NumberColumn("時価総額"),
    },
    ...
)
```

## エラーハンドリング・エッジケース

| 事象 | 挙動 |
| --- | --- |
| LLMが`SECTOR_MAP`に存在しない業種名を出力した場合 | `apply_filters`で単純な文字列等号比較のため、一致する行がなければ結果0件になる（既存の「未知フィールドは無視」とは異なり、ここではfieldは正しいがvalueが不一致というだけなので、エラーにはせず結果0件として扱う） |
| `UNIVERSE`の銘柄が`SECTOR_MAP`に存在しない場合 | `.map()`で`NaN`になる。現状`SECTOR_MAP`は`UNIVERSE`全銘柄をカバーしているため実運用では発生しない想定だが、発生しても既存の`per`等と同様に`notna()`チェックのある条件では自然に除外される |
| 業種条件を含まない自然言語条件（従来通りPER等のみ） | `sectors`一覧がプロンプトに含まれても、LLMが`sector`フィールドを使わなければ従来通りの挙動 |

## テスト方針

- `tests/test_screening.py`に追加:
  - `apply_filters`が`sector`フィールドの等号フィルタで正しく絞り込めることを確認するテスト（既存の`per`/`dividend_yield_pct`のテストと同じパターン）
  - `build_screening_prompt`に`sectors`を渡した場合、返り値の文字列に業種一覧と`sector`フィールドの説明が含まれることを確認するテスト
  - `build_screening_prompt`に`sectors`を渡さない場合（デフォルト`None`）、従来通りのプロンプトになる（業種一覧行が含まれない）ことを確認するテスト
- UI（業種列の表示）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`でスクリーニングタブから「自動車株でPERが低い銘柄」のような条件を入力し、AIが解釈した条件に`sector`フィールドが含まれること、絞り込み結果に業種列が表示されることを手動確認する

## v1スコープ外（将来課題）

- 業種専用のドロップダウン/マルチセレクトUI
- 業種の部分一致・複数業種指定（OR条件）
