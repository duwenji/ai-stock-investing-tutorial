# スクリーニング業種フィルタ対応 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** スクリーニングタブの自然言語条件で、業種（東証17業種区分）による絞り込みもできるようにする。

**Architecture:** 既存の`screening/sectors.py`の`SECTOR_MAP`（銘柄コード→業種）をスクリーニング用ユニバースDataFrameにマージして`sector`列を追加する。`prompt_patterns/screening.py`の`build_screening_prompt()`に有効な業種名一覧を渡し、LLMが自由記述の業種表現を正確な業種名にマッピングして`{"field": "sector", "operator": "==", "value": "..."}`形式のフィルタを出力できるようにする。`apply_filters()`は既にfieldのホワイトリスト方式で汎用的に動作するため変更不要。

**Tech Stack:** Python, Streamlit, pandas, pytest, uv（既存プロジェクトの構成をそのまま使用。新規pip依存追加なし）

## Global Constraints

- 新規pip依存を追加しない
- LLMに許可するfieldは`per`・`pbr`・`dividend_yield_pct`・`sector`の4つ（[design doc](../specs/2026-07-25-screening-sector-filter-design.md)参照）
- `sector`のoperatorは`==`のみ想定する（`apply_filters`自体は他のoperatorも技術的には通すが、プロンプト側で`==`のみ使うよう指示する）
- 業種名はfree-formの部分一致ではなく、`SECTOR_MAP`の値と完全一致した場合のみヒットする（一致しなければ結果0件、エラーにはしない）
- 業種専用のドロップダウン/マルチセレクトUIは追加しない（v1スコープ外）
- UI（Streamlit）の自動テストは書かない。既存プロジェクト方針どおり`uv run python -m streamlit run app.py`での手動確認とする
- テスト実行コマンド: `uv run pytest -v`（作業ディレクトリは`ai-stock-investing-tutorial/app`）

---

## File Structure

- Modify: `prompt_patterns/screening.py` — `build_screening_prompt()`に`sectors`引数を追加
- Modify: `tests/test_screening.py` — `build_screening_prompt`の業種一覧対応テスト、`apply_filters`の`sector`等号フィルタテストを追加
- Modify: `app.py` — ユニバースDataFrameへの`sector`列マージ、`build_screening_prompt`呼び出しへの業種一覧引き渡し、結果表への「業種」列追加

---

### Task 1: `build_screening_prompt()`の業種対応

**Files:**
- Modify: `prompt_patterns/screening.py:22-32`
- Test: `tests/test_screening.py`

**Interfaces:**
- Consumes: なし（標準ライブラリのみ）
- Produces: `build_screening_prompt(condition_text: str, sectors: list[str] | None = None) -> str`。Task 2はこのシグネチャで呼び出す

- [ ] **Step 1: Write the failing tests**

`tests/test_screening.py`の先頭import行を次のように変更する（`build_screening_prompt`を追加）:

```python
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)
```

ファイル末尾に以下のテストを追加する:

```python
def test_apply_filters_matches_sector_equality():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "自動車・輸送機"},
            {"ticker": "BBB", "sector": "銀行"},
        ]
    )
    filters = [{"field": "sector", "operator": "==", "value": "自動車・輸送機"}]
    result = apply_filters(df, filters)
    assert result["ticker"].tolist() == ["AAA"]


def test_build_screening_prompt_includes_sector_list_when_given():
    prompt = build_screening_prompt(
        "自動車株でPERが低い銘柄", sectors=["自動車・輸送機", "銀行"]
    )
    assert "sector" in prompt
    assert "自動車・輸送機" in prompt
    assert "銀行" in prompt
    assert "業種名のいずれか一つ" in prompt


def test_build_screening_prompt_omits_sector_list_when_not_given():
    prompt = build_screening_prompt("PERが15倍以下")
    assert "sector" in prompt  # fieldとしての説明自体は常に含まれる
    assert "業種名のいずれか一つ" not in prompt  # 業種一覧の案内文は含まれない
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `ai-stock-investing-tutorial/app`): `uv run pytest tests/test_screening.py -v`
Expected: `test_apply_filters_matches_sector_equality`はPASS（`apply_filters`は既に汎用実装のため）。`test_build_screening_prompt_includes_sector_list_when_given`と`test_build_screening_prompt_omits_sector_list_when_not_given`は`TypeError: build_screening_prompt() got an unexpected keyword argument 'sectors'`または`業種名のいずれか一つ`が含まれずFAIL

- [ ] **Step 3: Write the implementation**

`prompt_patterns/screening.py:22-32`の`build_screening_prompt`を次に置き換える:

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
        'sectorのoperatorは"=="のみ使用してください。\n'
        '出力形式: [{"field": "per", "operator": "<=", "value": 15}] の'
        "ようなJSON配列のみを出力してください。説明文やコードブロック記法は不要です。\n\n"
        f"条件: {condition_text}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_screening.py -v`
Expected: 全テストPASS（既存6件 + 新規3件 = 9件）

- [ ] **Step 5: Commit**

```bash
git add prompt_patterns/screening.py tests/test_screening.py
git commit -m "$(cat <<'EOF'
Let screening prompt filter by sector

build_screening_prompt() now accepts a list of valid sector names so
the LLM can map free-form phrases like "automotive stocks" onto the
exact sector value apply_filters() needs for an equality match.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `app.py`でのユニバース業種列マージとUI反映

**Files:**
- Modify: `app.py:487-489`（`build_screening_prompt`呼び出し）
- Modify: `app.py:509-514`（ユニバースDataFrame組み立て）
- Modify: `app.py:531-544`（結果表の`column_config`）

**Interfaces:**
- Consumes: `prompt_patterns.screening.build_screening_prompt(condition_text, sectors=...)`（Task 1で実装済み）、`screening.sectors.SECTOR_MAP`（`app.py:48`で既にimport済み）
- Produces: なし（このタスクが最終タスク）

- [ ] **Step 1: `build_screening_prompt`呼び出しに業種一覧を渡す**

`app.py:488`を次のように変更する:

変更前:
```python
            prompt = build_screening_prompt(condition_text)
```

変更後:
```python
            prompt = build_screening_prompt(
                condition_text, sectors=sorted(set(SECTOR_MAP.values()))
            )
```

- [ ] **Step 2: ユニバースDataFrameに`sector`列を追加**

`app.py:509-514`を次のように変更する:

変更前:
```python
            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                    universe_df["name"]
                )
                result_df = apply_filters(universe_df, filters)
```

変更後:
```python
            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                    universe_df["name"]
                )
                universe_df["sector"] = universe_df["ticker"].map(SECTOR_MAP)
                result_df = apply_filters(universe_df, filters)
```

- [ ] **Step 3: 結果表に「業種」列を追加**

`app.py:531-544`の`st.dataframe`呼び出しの`column_config`に`sector`を追加する:

変更前:
```python
        event = st.dataframe(
            result_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "per": st.column_config.NumberColumn("PER"),
                "pbr": st.column_config.NumberColumn("PBR"),
                "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                "market_cap": st.column_config.NumberColumn("時価総額"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="screening_result_table",
        )
```

変更後:
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
            on_select="rerun",
            selection_mode="single-row",
            key="screening_result_table",
        )
```

- [ ] **Step 4: 既存の自動テストが壊れていないことを確認**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS（`app.py`はUI自動テスト対象外だが、他モジュールへの影響がないことを確認する）

- [ ] **Step 5: アプリを起動して動作確認**

Run: `uv run python -m streamlit run app.py`

確認項目:
1. 「スクリーニング」タブで「自動車株でPERが低い銘柄」のような条件を入力し、「AIが解釈した条件」に`{"field": "sector", "operator": "==", "value": "自動車・輸送機"}`のようなフィルタが含まれることを確認する
2. 「この条件で絞り込む」を押し、絞り込み結果の一覧表に「業種」列が表示され、該当銘柄が正しい業種（例: トヨタ自動車なら「自動車・輸送機」）になっていることを確認する
3. 業種に言及しない従来通りの条件（例: 「PERが15倍以下」）でも、これまで通り問題なく絞り込めることを確認する（回帰確認）
4. 存在しない/曖昧な業種名を含む条件（例: 「宇宙開発株」）を入力した場合、結果が0件になってもエラー画面にならず「絞り込み結果（0件）」と表示されることを確認する

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Wire sector filtering into the screening tab

Merges the SECTOR_MAP lookup into the universe fundamentals table,
passes the valid sector names to the LLM prompt, and shows the
resulting sector column in the screening results table.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
