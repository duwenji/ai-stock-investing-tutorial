# 日経225ユニバース拡張 設計書

## 概要・目的

現状、スクリーニング・単一銘柄バックテスト・一括バックテストの3タブが共通で参照する `screening/universe.py` の `UNIVERSE` は主要60銘柄に限定されている。これから実装する「セクターローテーション分析」（別設計書 `2026-07-20-sector-rotation-design.md` で扱う）は業種ごとの値動きを比較するため、業種あたりの構成銘柄数が十分でないと分析の精度・説得力が下がる。現状のUNIVERSEは60銘柄中20銘柄が「電気機器」に偏っており、業種によっては1銘柄しかない。

本設計では `UNIVERSE` を「既存60銘柄 ∪ 日経225の225銘柄」の和集合に拡張し、業種分布を広げるとともに、既存3タブの対象範囲そのものを拡大する。既存60銘柄には日経225の正式構成銘柄か確証が持てないものが含まれる（例: `285A` キオクシアホールディングス、`6890` フェローテックホールディングス、`7729` 東京精密）ため、単純な差し替えではなく和集合とすることで、既存銘柄が漏れなく残ることを保証する。

## スコープ

- v1で実装する:
  - `screening/universe.py` の `UNIVERSE` / `UNIVERSE_NAMES` を「既存60銘柄 ∪ 日経225の225銘柄」の和集合（重複除く、225〜約230銘柄の見込み）に拡張
  - `data_api/stock_price_api.py` の `fetch_universe_fundamentals` を逐次ループから `common/concurrency.map_concurrently` を使った並列取得に変更（スクリーニングタブの初回実行時間対策）
  - `tests/test_universe.py` をUNIVERSE件数・重複なし・全件が `UNIVERSE_NAMES` に存在することを検証する内容に更新
- v1で実装しない（将来課題）:
  - 日経225構成銘柄の定期自動更新（銘柄入れ替えへの追随は手動メンテナンス）
  - 東証プライム全銘柄・TOPIX500など他のユニバースへの対応

## データ変更 — `screening/universe.py`

### 銘柄リストの作成方法

- Claude（実装時点の知識）が把握している日経225構成銘柄（コード・銘柄名）をもとにリストを作成する
- 作成した225コードすべてを `app/docs/data_j.xls`（JPX公式全銘柄一覧、既存ファイル）に対して突合し、以下を検証する:
  - 全コードが `data_j.xls` に実在すること（廃止・上場廃止銘柄が紛れていないか）
  - 銘柄名が一致すること（社名変更等の反映漏れがないか）
- 突合はスクリプトで一括検証し、不一致があれば実装時に手動で修正する（`data_j.xls` 自体は業種区分の取得にも使うため、この検証作業は次のセクターローテーション設計での業種マッピング作業と合わせて行う）
- 新しい `UNIVERSE` は「既存60銘柄のリスト ∪ 日経225の225銘柄リスト」の和集合とし、重複するティッカーは1件にまとめる（既存60銘柄のうち大半は日経225にも含まれる見込みだが、含まれないものがあっても和集合により必ず残る）
- ファイル冒頭に以下の趣旨のコメントを1行加える:
  > UNIVERSEは実装時点（2026年7月）の日経225構成銘柄と既存銘柄の和集合。日経225側は日本経済新聞社による定期見直し・臨時入れ替えで変動するため、定期的に公式発表と照合すること。

### 変更対象

```python
UNIVERSE: list[str] = [...]          # 60銘柄 → 既存60銘柄 ∪ 日経225(225銘柄)、重複除く225〜約230銘柄
UNIVERSE_NAMES: dict[str, str] = {...}  # 60銘柄分 → 同上の件数分
```

構造・型は変更しない（`list[str]` / `dict[str, str]`）ため、これらを参照する既存コード（`ticker_names.py`、`app.py` の各タブ）はロジック変更不要。

## 既存機能への影響と対応

### 1. スクリーニング（`fetch_universe_fundamentals`）

現状 `data_api/stock_price_api.py` の `fetch_universe_fundamentals` は対象銘柄を `for` ループで逐次 `fetch_fundamentals` 呼び出ししている。225〜約230銘柄になると初回実行（当日キャッシュなし時）が数分規模になりうるため、一括バックテスト（`app.py` 内 `map_concurrently` 使用箇所）と同じ並列化パターンを適用する。

変更前:
```python
rows = []
for ticker_symbol in tickers:
    data = fetch_fundamentals(ticker_symbol)
    rows.append({...})
```

変更後（`common.concurrency.map_concurrently` を使用、新規依存追加なし）:
```python
from common.concurrency import map_concurrently

results = map_concurrently(tickers, fetch_fundamentals)
rows = []
for ticker_symbol in tickers:
    data = results[ticker_symbol]
    if isinstance(data, Exception):
        continue  # 取得失敗銘柄はスキップ（既存の銘柄単位防御的実装を踏襲）
    rows.append({...})
```

キャッシュキー・キャッシュ形式（`universe-<hash>` のDataFrame JSON化）は変更しない。

### 2. 単一銘柄バックテスト

銘柄選択肢（セレクトボックス）の候補が225〜約230件に増えるのみ。バックテストロジック・キャッシュキー構造は変更不要。

### 3. 一括バックテスト

`target_tickers = UNIVERSE ∪ 保有銘柄` が225〜約230件規模に拡大する。この処理は既に `map_concurrently` で並列取得済み（`app.py:520`）のためコード変更は不要。初回のキャッシュ生成時間が伸びる点は許容事項として扱う（当日2回目以降はキャッシュヒットで即時表示）。

### 4. ポートフォリオの銘柄名補完（`ticker_names.py`）

`UNIVERSE_NAMES` が拡大するだけで `build_candidate_names` のロジック変更は不要。

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| `fetch_universe_fundamentals` で個別銘柄のyfinance取得が例外 | その銘柄の行を結果から除外し処理継続（既存の「フィルタ全体を失敗させない」防御的方針を踏襲） |
| 日経225リストと `data_j.xls` の突合で不一致（廃止銘柄・社名相違） | 実装時に手動修正。本番運用開始後に発覚した場合はコード側の注記コメントに従い随時更新 |

## テスト方針

- `tests/test_universe.py`:
  - `UNIVERSE` の件数が225件以上であること（既存60銘柄 ∪ 日経225の和集合であることの下限チェック）
  - `UNIVERSE` に重複がないこと
  - `UNIVERSE` の全ティッカーが `UNIVERSE_NAMES` のキーに存在すること
  - 変更前の60銘柄（実装時点でのリテラル値、または変更前コミットから抽出した固定リスト）がすべて新しい `UNIVERSE` に含まれること（和集合の保証を回帰的に検証）
- `tests/test_stock_price_api.py`:
  - `fetch_universe_fundamentals` を並列化した後も、モック化した `fetch_fundamentals` を使って戻り値のDataFrame形状・キャッシュ書き込み内容が既存仕様と変わらないことを確認
  - 一部銘柄で `fetch_fundamentals` が例外を送出するケースをモックし、その銘柄が結果から除外され他の銘柄の処理が継続することを確認
- UI動作（初回スクリーニング実行時間・225〜約230件の選択肢表示）は `uv run python -m streamlit run app.py` で手動確認

## v1スコープ外（将来課題）

- 日経225銘柄入れ替えの自動追随
- 東証プライム全銘柄・TOPIX500など他ユニバースの選択式対応
