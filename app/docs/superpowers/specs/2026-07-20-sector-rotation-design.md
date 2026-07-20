# セクターローテーション分析 設計書

## 概要・目的

経済には循環（景気サイクル）があり、業種（セクター）ごとに値動きのタイミングがずれる「セクターローテーション」が経験的に知られている。本機能では、[日経225ユニバース拡張](2026-07-20-nikkei225-universe-expansion-design.md)で拡張したUNIVERSE（228銘柄）を17業種に分類し、業種間の値動きの時間差相関（リード・ラグ）を株価データから計算して可視化する。「今どの業種が先行し、どの業種が何営業日遅れて追随する傾向にあるか」を提示し、取引判断の参考情報とする。

既存タブと同じ設計方針を踏襲する: 事実データの計算はPython側で行い、その解釈・考察のみをAI（Claude Code CLI）に生成させる。売買の推奨・指示は行わない（[DISCLAIMER.md](../../../../DISCLAIMER.md) 準拠）。景気サイクルの局面判定に外部マクロ指標（GDP・景気動向指数等）は使用せず、株価データのみから計算する。

## スコープ

- v1で実装する:
  - `screening/sectors.py`: UNIVERSE全228銘柄を17業種区分に分類する`SECTOR_MAP`
  - `sector_analysis/correlation.py`: 業種別リターン系列の算出、業種ペアごとの時差相関（リード・ラグ）計算
  - `prompt_patterns/sector_rotation.py`: 相関上位ペアについてのAI考察プロンプト生成
  - `app.py`: 新タブ「セクターローテーション」（期間選択・相関ヒートマップ・リード/ラグ表・AIコメント）
  - 日次キャッシュ（既存`common/cache.py`の方式を踏襲）
- v1で実装しない（将来課題）:
  - 外部マクロ経済指標（GDP・景気動向指数等）の取得・統合
  - 業種ペアごとの詳細ドリルダウン（個別銘柄レベルでの寄与度分析）
  - 33業種区分への切り替えオプション
  - リアルタイム・自動更新（既存タブと同様、ボタン押下時のみ計算）

## データ変更 — `screening/sectors.py`（新設）

### SECTOR_MAPの作成方法

- `app/docs/data_j.xls`（JPX公式全銘柄一覧）の17業種区分列から、UNIVERSE228銘柄のうち227銘柄分を抽出する
- `543A`（ARCHION、2026年4月上場のため`data_j.xls`未収録）のみ手動で`"自動車・輸送機"`を割り当てる（日野自動車と三菱ふそうの経営統合会社のため）
- 実装時点でUNIVERSE228銘柄は以下の17業種すべてに分布する（検証済み、多い順）:

  | 業種 | 銘柄数 |
  | --- | --- |
  | 電機・精密 | 39 |
  | 情報通信・サービスその他 | 27 |
  | 素材・化学 | 19 |
  | 機械 | 17 |
  | 建設・資材 | 16 |
  | 運輸・物流 | 15 |
  | 自動車・輸送機 | 13（`543A`手動割当て後） |
  | 食品 | 11 |
  | 小売 | 11 |
  | 鉄鋼・非鉄 | 10 |
  | 銀行 | 10 |
  | 金融（除く銀行） | 10 |
  | 医薬品 | 9 |
  | 商社・卸売 | 7 |
  | 不動産 | 5 |
  | 電力・ガス | 5 |
  | エネルギー資源 | 3 |

### 変更対象

```python
# SECTOR_MAPはUNIVERSE(screening/universe.py)の全銘柄を17業種区分（東証）に分類したもの。
# app/docs/data_j.xls（JPX公式全銘柄一覧）から抽出。543A（ARCHION、2026年4月上場）のみ
# data_j.xlsに未収録のため手動割当て。UNIVERSE更新時はこのファイルも合わせて更新すること。
SECTOR_MAP: dict[str, str] = {
    "1332.T": "食品",
    # ...（228件、UNIVERSEの全ティッカーを網羅）
}
```

`SECTOR_MAP`のキー集合は`UNIVERSE`と完全一致する（テストで保証する）。

## コアロジック — `sector_analysis/correlation.py`（新設）

### `compute_sector_returns`

```python
def compute_sector_returns(
    prices_by_ticker: dict[str, pd.Series],
    sector_map: dict[str, str],
) -> dict[str, pd.Series]:
    """業種ごとに構成銘柄の日次リターンを等ウエイト平均した系列を返す。

    prices_by_tickerに存在しない、またはNoneの銘柄はスキップする。
    構成銘柄が0件になった業種はキーごと結果から除外する。
    """
```

- 各銘柄の終値系列から`pct_change()`で日次リターンを算出
- 業種ごとに、構成銘柄の日次リターンを日付インデックスで揃えて等ウエイト平均（`DataFrame.mean(axis=1)`、欠損は`skipna=True`）
- 戻り値は`{業種名: 日次リターン系列(pd.Series)}`

### `compute_lead_lag_pairs`

```python
def compute_lead_lag_pairs(
    sector_returns: dict[str, pd.Series],
    max_lag_days: int = 20,
) -> list[dict]:
    """業種の全ペア（重複なし）について、時差相関が最大となるラグを求める。

    戻り値の各要素:
        {
            "leading_sector": str,   # 先行する業種
            "lagging_sector": str,   # 追随する業種
            "lag_days": int,         # 0以上。0は同時（タイの場合は業種名の昇順でleading/laggingを決定）
            "correlation": float,    # 最適ラグでの相関係数（符号付き）
        }
    相関係数の絶対値が大きい順にソートして返す。
    """
```

- 業種ペア (X, Y) について、`lag`を`-max_lag_days`から`max_lag_days`まで動かし、`X.corr(Y.shift(lag))`を計算する
  - `Y.shift(lag)`は「`lag`日前のYの値」を現在の日付に揃えたもの。`lag > 0`のとき「Yの過去の値」と「Xの現在の値」の相関を見ることになるため、相関が高ければ**Yが先行しXが追随**（lag日遅れ）と解釈する
  - `lag < 0`の場合は逆に**Xが先行しYが追随**（`|lag|`日遅れ）
- 相関の絶対値が最大となる`lag`を採用し、`leading_sector`/`lagging_sector`/`lag_days`（常に0以上の値に正規化）/`correlation`を1レコードとして記録
- 業種数が17の場合、136ペア（17×16÷2）を返す
- 系列の重なりが不十分（共通の非欠損日数が`max_lag_days`未満）なペアは結果から除外する

## UI設計 — `app.py`

新タブ「セクターローテーション」を既存4タブの末尾に追加する。

```python
tab_portfolio, tab_screening, tab_backtest, tab_ranking, tab_sector = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト", "セクターローテーション"]
)
```

### 操作フロー

1. 期間セレクトボックス（`6mo` / `1y` / `2y`、デフォルト`1y`）
2. 「キャッシュを無視して再生成する」チェックボックス
3. 「分析を実行」ボタン押下で以下を実行:
   - `cache_key = "sector-rotation-" + sha256(f"{period}-{'-'.join(sorted(UNIVERSE))}")`
   - キャッシュヒット時はキャッシュ済みpayloadを使用
   - キャッシュミス時:
     - `map_concurrently(UNIVERSE, lambda t: _cached_fetch_price_history(t, period))`でUNIVERSE全228銘柄の株価履歴を並列取得（一括バックテストタブと同一パターン、進捗は`st.spinner`表示）
     - 取得失敗・空データの銘柄は`skipped_tickers`に記録しスキップ
     - `compute_sector_returns(prices_by_ticker, SECTOR_MAP)` → 業種別リターン系列
     - 構成銘柄が0件の業種があれば、その業種名を`excluded_sectors`として記録
     - `compute_lead_lag_pairs(sector_returns, max_lag_days=20)` → 相関上位ペア一覧
     - 相関上位5ペアについて`generate_sector_rotation_comments`でAIコメントを1回のプロンプトでバッチ生成
     - `payload = {"pairs": ..., "skipped_tickers": ..., "excluded_sectors": ..., "comments": ...}`をキャッシュに書き込む
4. 結果表示:
   - **相関ヒートマップ**: 17×17（または実際に構成銘柄が存在する業種数×同数）の対称行列を、Altairの`mark_rect`で描画（各セルは業種ペアの最適ラグにおける相関係数の絶対値、対角線は1）。新規依存追加なし（既存の[ローソク足チャート](2026-07-20-stock-detail-candlestick-design.md)と同じくAltairを使用）
   - **リード・ラグ表**: `st.dataframe`で「先行業種」「追随業種」「ラグ（営業日）」「相関係数」列を相関の強い順に表示
   - **AIコメント**: 相関上位5ペアについて「先行業種名 → 追随業種名」見出しでコメント文を表示
   - スキップ銘柄・除外業種があればその一覧を表示
   - 末尾に`DISCLAIMER_NOTICE`を表示

## プロンプト設計 — `prompt_patterns/sector_rotation.py`（新設）

```python
def build_sector_rotation_prompt(top_pairs: list[dict]) -> str: ...

def generate_sector_rotation_comments(
    top_pairs: list[dict],
    call_llm=call_llm,
) -> dict[str, str]:
    """top_pairsの各要素に対しコメントを生成する。

    キーは f"{leading_sector}->{lagging_sector}" の文字列。
    JSONパース失敗時は全ペアに対し「コメント生成失敗」を返す（既存パターン踏襲）。
    """
```

- プロンプトには「1. 過去データ上の相関・ラグの傾向の説明 2. あくまで過去の統計的傾向であり将来を保証しないことの明示 3. 売買の指示・推奨をしないこと」を必須項目として明示する（既存の`backtest_explanation.py`のプロンプト設計方針を踏襲）
- 相関上位5ペアをまとめて1回のプロンプトでバッチ処理する（既存の`generate_ranking_comments`と同一パターン、サブプロセス起動オーバーヘッド対策）

## キャッシュ

- キー: `sector-rotation-{period}-{UNIVERSE全体のハッシュ}`（UNIVERSEは固定銘柄集合のため、事実上「期間」のみが変動要素）
- 既存`common/cache.py`をそのまま利用、当日分キャッシュ、「キャッシュを無視して再生成する」チェックボックスで無視可能

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| 個別銘柄の株価取得失敗（例外・空データ） | `skipped_tickers`に記録しスキップ、処理継続 |
| 業種の構成銘柄が0件（該当銘柄が全てスキップ） | その業種を`excluded_sectors`として分析から除外 |
| 業種ペアの共通データ日数が`max_lag_days`未満 | そのペアを`compute_lead_lag_pairs`の結果から除外 |
| AIコメントのJSONパース失敗 | 該当ペア全件に「コメント生成失敗」を表示（他の表示は継続） |
| 取得できた銘柄が0件 | 「分析可能な銘柄がありませんでした」エラー表示、以降の処理を行わない |

## テスト方針

- `tests/test_sectors.py`: `SECTOR_MAP`のキー集合が`UNIVERSE`と完全一致すること、値が全て非空文字列であることを検証
- `tests/test_sector_correlation.py`:
  - `compute_sector_returns`: 複数銘柄の等ウエイト平均が正しく計算されること、欠損銘柄のスキップ、構成銘柄0件業種の除外
  - `compute_lead_lag_pairs`: 既知のラグを人工的に仕込んだ2系列（例: 系列Bを系列Aから5日シフトして作成）で、最適ラグが期待通り検出されること、相関係数の符号・`leading_sector`/`lagging_sector`の向きが正しいこと、データ不足ペアの除外
- `tests/test_sector_rotation_prompt.py`: `build_sector_rotation_prompt`が売買指示をしない旨を含むこと、`generate_sector_rotation_comments`のJSON成功時・パース失敗時のフォールバック
- UI（ヒートマップ描画・タブ操作）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`で手動確認する

## v1スコープ外（将来課題）

- 外部マクロ経済指標との統合
- 33業種区分への切り替え
- 個別銘柄レベルのドリルダウン分析
- リアルタイム自動更新
