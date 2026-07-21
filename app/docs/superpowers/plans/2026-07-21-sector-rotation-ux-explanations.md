# セクターローテーション UI説明強化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** セクターローテーションタブの各ウィジェット・セクションに`help`ツールチップと2つの`st.expander`による詳細解説を追加し、専門用語（コヒーレンス・周期帯・リード・ラグ等）の意味をユーザーが理解しやすくする。

**Architecture:** `app.py`の`with tab_sector:`ブロックのみを変更する。ロジック・計算内容・データ構造は一切変更しない、純粋なUI文言追加。

**Tech Stack:** Python 3.14, streamlit>=1.59.2（`help`引数・`st.expander`は既存バージョンで利用可能、新規依存なし）

## Global Constraints

- ロジック・計算内容の変更は行わない（`sector_analysis/correlation.py`, `sector_analysis/wavelet.py`, `prompt_patterns/sector_rotation.py`は変更しない）
- `app.py`の`with tab_sector:`ブロック以外は変更しない
- 新規の実行時依存は追加しない
- 新規の自動テストは追加しない（`app.py`は既存方針により自動テスト対象外）。既存の`uv run pytest`が全件PASSすることのみ確認する
- 他タブへの説明追加、用語集ページ、多言語化はv1スコープ外（本計画では実施しない）

---

### Task 1: セクターローテーションタブに`help`ツールチップと解説`expander`を追加する

**Files:**
- Modify: `app.py:718-725`, `app.py:802`, `app.py:818-833`, `app.py:843-850`, `app.py:861-875`, `app.py:930-932`（行番号は現状のもの。前の編集が反映されるとズレるため、各ステップでは対象コードのテキスト内容で特定すること）

**Interfaces:**
- Consumes: なし（既存のセクターローテーションタブのコードのみを対象にした文言追加）
- Produces: なし（UI文言の追加のみ、他タスクから参照されるインターフェースはない）

このタスクはUI文言（`help`引数・`st.expander`）の追加のみで、ロジック変更を伴わないため、既存方針（`app.py`は自動テスト対象外・手動確認）に従いTDDステップは適用しない。

- [x] **Step 1: 取得期間・キャッシュチェックボックス・分析実行ボタンに`help`を追加する**

現状（`app.py`）:
```python
    sector_period = st.selectbox(
        "取得期間", ["6mo", "1y", "2y"], index=1, key="sector_period"
    )
    sector_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="sector_force_regenerate"
    )

    if st.button("分析を実行"):
```

変更後:
```python
    sector_period = st.selectbox(
        "取得期間",
        ["6mo", "1y", "2y"],
        index=1,
        key="sector_period",
        help=(
            "株価データを取得する期間です。長いほど長期の周期（サイクル）分析の"
            "精度が上がりますが、取得に時間がかかります。"
        ),
    )
    sector_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する",
        key="sector_force_regenerate",
        help=(
            "前回と同じ期間で分析済みの場合、通常は保存済みの結果を再利用します。"
            "最新データで計算し直したいときにチェックしてください。"
        ),
    )

    if st.button(
        "分析を実行",
        help=(
            "初回実行時は228銘柄のデータ取得のため30秒程度かかります"
            "（2回目以降はキャッシュにより高速です）。"
        ),
    ):
```

- [x] **Step 2: 「業種間相関ヒートマップ」見出しに`help`を追加する**

現状:
```python
            st.subheader("業種間相関ヒートマップ")
```

変更後:
```python
            st.subheader(
                "業種間相関ヒートマップ",
                help=(
                    "17業種の組み合わせについて、最も強く連動するタイミング"
                    "（リード・ラグ）における相関の強さを、色の濃さで示します。"
                ),
            )
```

- [x] **Step 3: 「リード・ラグ上位ペア」見出しに`help`を追加し、表の直後に「リード・ラグの読み方」expanderを追加する**

現状:
```python
            st.subheader("リード・ラグ上位ペア")
            pairs_df = pd.DataFrame(pairs)[
                ["leading_sector", "lagging_sector", "lag_days", "correlation"]
            ]
            st.dataframe(
                pairs_df,
                column_config={
                    "leading_sector": st.column_config.TextColumn("先行業種"),
                    "lagging_sector": st.column_config.TextColumn("追随業種"),
                    "lag_days": st.column_config.NumberColumn("ラグ（営業日）"),
                    "correlation": st.column_config.NumberColumn("相関係数"),
                },
                hide_index=True,
            )

            st.subheader("相関上位5ペアのAIコメント")
```

変更後:
```python
            st.subheader(
                "リード・ラグ上位ペア",
                help=(
                    "相関が強い順に、どちらの業種が何営業日先行して動く傾向が"
                    "あったかを一覧表示します。"
                ),
            )
            pairs_df = pd.DataFrame(pairs)[
                ["leading_sector", "lagging_sector", "lag_days", "correlation"]
            ]
            st.dataframe(
                pairs_df,
                column_config={
                    "leading_sector": st.column_config.TextColumn("先行業種"),
                    "lagging_sector": st.column_config.TextColumn("追随業種"),
                    "lag_days": st.column_config.NumberColumn("ラグ（営業日）"),
                    "correlation": st.column_config.NumberColumn("相関係数"),
                },
                hide_index=True,
            )

            with st.expander("リード・ラグの読み方"):
                st.markdown(
                    "「先行業種」の値動きに、「追随業種」が「ラグ（営業日）」で"
                    "示した日数だけ遅れて追随する傾向が、指定した期間の株価データ"
                    "から確認されたことを示します。\n\n"
                    "例えば「先行業種: 建設・資材、追随業種: 機械、ラグ: 0日、"
                    "相関係数: 0.87」であれば、建設・資材セクターの値動きと"
                    "機械セクターの値動きが、同じ営業日にほぼ同じ方向へ動く傾向が"
                    "強かったことを意味します。\n\n"
                    "**注意:** 上位ペアの多くはラグ0日（同時相関）になりやすい"
                    "傾向があります。これは業種固有の先行・追随関係というより、"
                    "市場全体の地合い（同じ日に多くの業種が一緒に動く傾向）を"
                    "反映している可能性があります。特定の周期の長さ"
                    "（短期・中期・長期）ごとに、より業種固有の先行・追随関係を"
                    "確認したい場合は、下部の「ウェーブレット分析」もあわせて"
                    "ご覧ください。"
                )

            st.subheader(
                "相関上位5ペアのAIコメント",
                help=(
                    "上記の上位5ペアについて、過去データ上の傾向をAIが解説した"
                    "ものです。売買の推奨ではありません。"
                ),
            )
```

- [x] **Step 4: 「ウェーブレット分析」見出しに`help`を追加し、caption直後に「ウェーブレット分析とは？」expanderを追加する**

現状:
```python
        st.subheader("ウェーブレット分析（時間変化するリード・ラグ）")
        st.caption(
            "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
            "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
            "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
        )

        sector_options = sorted(payload["sector_returns"].keys())
```

変更後:
```python
        st.subheader(
            "ウェーブレット分析（時間変化するリード・ラグ）",
            help="時間の経過とともに変化する、業種間の先行・追随関係を可視化します。",
        )
        st.caption(
            "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
            "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
            "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
        )
        with st.expander("ウェーブレット分析とは？"):
            st.markdown(
                "通常の相関分析は「期間全体で1つの数値」を計算しますが、実際の"
                "値動きには短い周期（数日〜2週間程度）の動きと、長い周期"
                "（1〜6か月程度）の動きが混ざっています。ウェーブレット分析は、"
                "この値動きを周期の長さ（短期・中期・長期）ごとに分解し、周期ごとに"
                "「どちらの業種が先に動いたか」「どれくらい確からしい関係か"
                "（コヒーレンス）」を計算する手法です。\n\n"
                "**周期帯の目安**\n"
                "- 短期: 4〜10営業日程度（1〜2週間の値動き）\n"
                "- 中期: 10〜40営業日程度（2週間〜2か月の値動き）\n"
                "- 長期: 40〜120営業日程度（2〜6か月の値動き）\n\n"
                "**下のヒートマップの読み方**\n"
                "- 横軸: 日付\n"
                "- 縦軸: 周期の長さ（営業日）\n"
                "- 色: 正（青系）なら業種Aが先行、負（赤系）なら業種Bが先行\n"
                "- 色の濃さ: 関係の確からしさ（コヒーレンス）。薄いほど確からしさが"
                "低く、参考程度に留めてください\n\n"
                "下部の「支配的ラグ」の折れ線グラフは、選んだ周期帯の中で"
                "コヒーレンスの高い部分を重視した、平均的な先行・遅行日数の推移を"
                "示します。0より上なら業種Aが先行、0より下なら業種Bが先行して"
                "いたことを意味します。"
            )

        sector_options = sorted(payload["sector_returns"].keys())
```

- [x] **Step 5: 業種A・業種Bのselectboxに`help`を追加する**

現状:
```python
            col_a, col_b = st.columns(2)
            with col_a:
                sector_x = st.selectbox(
                    "業種A",
                    sector_options,
                    index=sector_options.index(default_x),
                    key="wavelet_sector_x",
                )
            with col_b:
                sector_y = st.selectbox(
                    "業種B",
                    sector_options,
                    index=sector_options.index(default_y),
                    key="wavelet_sector_y",
                )
```

変更後:
```python
            col_a, col_b = st.columns(2)
            sector_select_help = (
                "比較したい2つの業種を選びます"
                "（デフォルトは相関上位ペアの先行・追随業種）。"
            )
            with col_a:
                sector_x = st.selectbox(
                    "業種A",
                    sector_options,
                    index=sector_options.index(default_x),
                    key="wavelet_sector_x",
                    help=sector_select_help,
                )
            with col_b:
                sector_y = st.selectbox(
                    "業種B",
                    sector_options,
                    index=sector_options.index(default_y),
                    key="wavelet_sector_y",
                    help=sector_select_help,
                )
```

- [x] **Step 6: 周期帯selectboxに`help`を追加する**

現状:
```python
                band = st.selectbox(
                    "周期帯", ["短期", "中期", "長期"], index=1, key="wavelet_band"
                )
```

変更後:
```python
                band = st.selectbox(
                    "周期帯",
                    ["短期", "中期", "長期"],
                    index=1,
                    key="wavelet_band",
                    help=(
                        "短期(4〜10営業日) / 中期(10〜40営業日) / 長期(40〜120営業日) "
                        "のいずれかを選び、その周期帯における支配的ラグの推移を"
                        "表示します。"
                    ),
                )
```

- [x] **Step 7: 構文チェックを行う**

Run: `cd app && uv run python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read())" && echo OK`
Expected: `OK`が出力される（構文エラーがない）

- [x] **Step 8: 既存テストスイートを実行し、副作用がないことを確認する**

Run: `cd app && uv run pytest -v`
Expected: 全件PASS（`app.py`はテスト対象外のため件数に変化はない。117件PASSのはず）

- [x] **Step 9: Streamlitアプリで手動確認する**

Run: `cd app && uv run python -m streamlit run app.py --server.headless true`

手順:
1. セクターローテーションタブを開き、「分析を実行」をクリックする（初回はキャッシュがあれば数秒、なければ数十秒）
2. 各ウィジェット（取得期間・キャッシュチェックボックス・分析実行ボタン・各`st.subheader`・業種A/B・周期帯）にホバーし、？アイコンとツールチップ文言が表示されることを確認する
3. 「リード・ラグ上位ペア」表の直後に「リード・ラグの読み方」というexpanderが表示され、初期状態では折りたたまれていること、クリックで開き、太字・箇条書きを含む説明文が正しくレンダリングされることを確認する
4. 「ウェーブレット分析」セクションのcaption直後に「ウェーブレット分析とは？」というexpanderが表示され、同様に開閉・レンダリングを確認する
5. ブラウザのコンソールにエラーが出ていないことを確認する

Expected: 上記すべてが問題なく表示・動作する

実施結果: `--server.headless true`で起動し、Playwright（Chromium）で実接続。ツールチップアイコン（`stTooltipHoverTarget`）が15個検出され、1つ目にホバーした際にポップアップ文言が正しく表示されることをスクリーンショットで確認した。「リード・ラグの読み方」「ウェーブレット分析とは？」の両expanderはクリックで開き、太字・箇条書きを含むMarkdownが崩れずレンダリングされた。`console --errors`相当のブラウザコンソール監視でエラーなし。

- [x] **Step 10: コミット**

```bash
cd app
git add app.py
git commit -m "docs: セクターローテーションタブにヘルプツールチップと解説expanderを追加"
```

---

## Global Constraintsの確認（実装完了時のチェックリスト）

- [x] `sector_analysis/correlation.py`・`sector_analysis/wavelet.py`・`prompt_patterns/sector_rotation.py`に変更がないこと
- [x] `app.py`の`with tab_sector:`ブロック以外に変更がないこと
- [x] 新規の実行時依存が追加されていないこと（`pyproject.toml`に差分がないこと）
- [x] `uv run pytest`が全件PASSすること（117件）
- [x] Streamlitアプリでツールチップ・expanderが正しく表示・動作すること（Step 9で確認）
