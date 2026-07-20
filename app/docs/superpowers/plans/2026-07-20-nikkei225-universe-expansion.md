# 日経225ユニバース拡張 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 共通`UNIVERSE`を、拡張前の既存60銘柄と日経225の全225銘柄の和集合（228銘柄）に拡張し、スクリーニングタブの銘柄データ取得を並列化する。

**Architecture:** `screening/universe.py`の`UNIVERSE`/`UNIVERSE_NAMES`のデータを差し替える。`data_api/stock_price_api.py`の`fetch_universe_fundamentals`は既存の`common/concurrency.map_concurrently`ヘルパー（一括バックテストで使用中のものを流用、新規実装不要）で並列化する。既存3タブ（スクリーニング・単一銘柄バックテスト・一括バックテスト）・`portfolio_management/ticker_names.py`はロジック変更不要。

**Tech Stack:** Python 3.14, pandas, yfinance, pytest, uv

## Global Constraints

- 新規の実行時依存追加なし（`xlrd`はデータ検証作業にのみ使用し、`pyproject.toml`には追加しない）
- `UNIVERSE`/`UNIVERSE_NAMES`の型は変更しない（`list[str]` / `dict[str, str]`）
- 拡張前の既存60銘柄はすべて新しい`UNIVERSE`に残る（和集合であること）
- キャッシュキー構造・キャッシュファイル形式（`universe-<hash>`、DataFrameのJSON化）は変更しない

---

### Task 1: UNIVERSEを日経225との和集合に拡張する

**Files:**
- Modify: `screening/universe.py`（全体差し替え）
- Test: `tests/test_universe.py`

**Interfaces:**
- Consumes: なし
- Produces: `UNIVERSE: list[str]`（228件、`"XXXX.T"`形式の東証ティッカー）、`UNIVERSE_NAMES: dict[str, str]`（同228件、`UNIVERSE`の全キーを網羅）。後続タスク・既存コード（`ticker_names.py`、`data_api/stock_price_api.py`、`app.py`の各タブ）はこの2シンボルをこれまで通りの型・意味で利用する。

- [x] **Step 1: 既存テストを新しい期待値に書き換える（失敗させる）**

`tests/test_universe.py` の内容を以下に置き換える:

```python
from screening.universe import UNIVERSE, UNIVERSE_NAMES

# 拡張前（既存60銘柄）のティッカー。和集合により必ず残ることを回帰的に検証する。
_PRE_EXPANSION_TICKERS = [
    "7203.T", "7267.T", "7201.T", "6758.T", "6861.T", "6501.T", "6503.T",
    "6752.T", "6902.T", "6971.T", "8035.T", "6273.T", "9432.T", "9433.T",
    "9434.T", "9984.T", "8306.T", "8316.T", "8411.T", "8766.T", "8058.T",
    "8031.T", "8001.T", "2914.T", "4502.T", "4519.T", "4568.T", "3382.T",
    "9843.T", "8267.T", "4901.T", "7751.T", "7011.T", "6301.T", "5108.T",
    "4063.T", "6367.T", "9020.T", "9022.T", "9101.T", "8801.T", "8802.T",
    "6098.T", "4661.T", "6857.T", "6920.T", "6146.T", "6723.T", "3436.T",
    "4062.T", "6981.T", "6762.T", "6963.T", "6702.T", "285A.T", "7735.T",
    "6701.T", "4004.T", "6890.T", "7729.T",
]


def test_universe_size_covers_nikkei225_and_existing():
    # 日経225(225件)と拡張前の既存60銘柄の和集合。重複57件を除くと228件になる。
    assert len(UNIVERSE) == 228


def test_universe_tickers_are_unique():
    assert len(UNIVERSE) == len(set(UNIVERSE))


def test_universe_tickers_use_tokyo_exchange_suffix():
    assert all(ticker.endswith(".T") for ticker in UNIVERSE)


def test_universe_names_cover_all_tickers():
    assert set(UNIVERSE_NAMES.keys()) == set(UNIVERSE)


def test_universe_names_have_non_empty_values():
    assert all(isinstance(name, str) and name for name in UNIVERSE_NAMES.values())


def test_universe_retains_all_pre_expansion_tickers():
    assert set(_PRE_EXPANSION_TICKERS) <= set(UNIVERSE)
```

- [x] **Step 2: テストを実行し、期待通り失敗することを確認する**

Run: `cd app && uv run pytest tests/test_universe.py -v`
Expected: `test_universe_size_covers_nikkei225_and_existing` が `assert 60 == 228` で FAIL。`test_universe_retains_all_pre_expansion_tickers` はUNIVERSE未変更のためPASSする（変更後も引き続きPASSすることを確認する用途）。

- [x] **Step 3: `screening/universe.py`を228銘柄のリストに差し替える**

`screening/universe.py` の内容を丸ごと以下に置き換える:

```python
# UNIVERSEは実装時点（2026年7月）の日経225構成銘柄と、拡張前の既存銘柄の和集合。
# 日経225側は日本経済新聞社による定期見直し・臨時入れ替えで変動するため、
# 定期的に https://indexes.nikkei.co.jp/nkave/index/component?idx=nk225 等の
# 公式発表と照合すること。
UNIVERSE: list[str] = [
    "1332.T",  # ニッスイ
    "1605.T",  # ＩＮＰＥＸ
    "1721.T",  # コムシスホールディングス
    "1801.T",  # 大成建設
    "1802.T",  # 大林組
    "1803.T",  # 清水建設
    "1808.T",  # 長谷工コーポレーション
    "1812.T",  # 鹿島建設
    "1925.T",  # 大和ハウス工業
    "1928.T",  # 積水ハウス
    "1963.T",  # 日揮ホールディングス
    "2002.T",  # 日清製粉グループ本社
    "2269.T",  # 明治ホールディングス
    "2282.T",  # 日本ハム
    "2413.T",  # エムスリー
    "2432.T",  # ディー・エヌ・エー
    "2501.T",  # サッポロホールディングス
    "2502.T",  # アサヒグループホールディングス
    "2503.T",  # キリンホールディングス
    "2768.T",  # 双日
    "2801.T",  # キッコーマン
    "2802.T",  # 味の素
    "285A.T",  # キオクシアホールディングス
    "2871.T",  # ニチレイ
    "2914.T",  # JT
    "3086.T",  # Ｊ．フロント　リテイリング
    "3092.T",  # ＺＯＺＯ
    "3099.T",  # 三越伊勢丹ホールディングス
    "3289.T",  # 東急不動産ホールディングス
    "3382.T",  # セブン&アイ・ホールディングス
    "3401.T",  # 帝人
    "3402.T",  # 東レ
    "3405.T",  # クラレ
    "3407.T",  # 旭化成
    "3436.T",  # SUMCO
    "3659.T",  # ネクソン
    "3697.T",  # ＳＨＩＦＴ
    "3861.T",  # 王子ホールディングス
    "4004.T",  # レゾナック・ホールディングス
    "4005.T",  # 住友化学
    "4021.T",  # 日産化学
    "4042.T",  # 東ソー
    "4043.T",  # トクヤマ
    "4061.T",  # デンカ
    "4062.T",  # イビデン
    "4063.T",  # 信越化学工業
    "4151.T",  # 協和キリン
    "4183.T",  # 三井化学
    "4188.T",  # 三菱ケミカルグループ
    "4208.T",  # ＵＢＥ
    "4307.T",  # 野村総合研究所
    "4324.T",  # 電通グループ
    "4385.T",  # メルカリ
    "4452.T",  # 花王
    "4502.T",  # 武田薬品工業
    "4503.T",  # アステラス製薬
    "4506.T",  # 住友ファーマ
    "4507.T",  # 塩野義製薬
    "4519.T",  # 中外製薬
    "4523.T",  # エーザイ
    "4543.T",  # テルモ
    "4568.T",  # 第一三共
    "4578.T",  # 大塚ホールディングス
    "4661.T",  # オリエンタルランド
    "4689.T",  # ＬＩＮＥヤフー
    "4704.T",  # トレンドマイクロ
    "4751.T",  # サイバーエージェント
    "4755.T",  # 楽天グループ
    "4901.T",  # 富士フイルムHD
    "4902.T",  # コニカミノルタ
    "4911.T",  # 資生堂
    "5019.T",  # 出光興産
    "5020.T",  # ＥＮＥＯＳホールディングス
    "5101.T",  # 横浜ゴム
    "5108.T",  # ブリヂストン
    "5201.T",  # ＡＧＣ
    "5214.T",  # 日本電気硝子
    "5233.T",  # 太平洋セメント
    "5301.T",  # 東海カーボン
    "5332.T",  # ＴＯＴＯ
    "5333.T",  # 日本碍子
    "5401.T",  # 日本製鉄
    "5406.T",  # 神戸製鋼所
    "5411.T",  # ＪＦＥホールディングス
    "543A.T",  # ARCHION
    "5631.T",  # 日本製鋼所
    "5706.T",  # 三井金属鉱業
    "5711.T",  # 三菱マテリアル
    "5713.T",  # 住友金属鉱山
    "5714.T",  # ＤＯＷＡホールディングス
    "5801.T",  # 古河電気工業
    "5802.T",  # 住友電気工業
    "5803.T",  # フジクラ
    "5831.T",  # しずおかフィナンシャルグループ
    "6098.T",  # リクルートHD
    "6103.T",  # オークマ
    "6113.T",  # アマダ
    "6146.T",  # ディスコ
    "6178.T",  # 日本郵政
    "6273.T",  # SMC
    "6301.T",  # コマツ
    "6302.T",  # 住友重機械工業
    "6305.T",  # 日立建機
    "6326.T",  # クボタ
    "6361.T",  # 荏原製作所
    "6367.T",  # ダイキン工業
    "6471.T",  # 日本精工
    "6472.T",  # ＮＴＮ
    "6473.T",  # ジェイテクト
    "6479.T",  # ミネベアミツミ
    "6501.T",  # 日立製作所
    "6503.T",  # 三菱電機
    "6504.T",  # 富士電機
    "6506.T",  # 安川電機
    "6526.T",  # ソシオネクスト
    "6532.T",  # ベイカレント
    "6594.T",  # ニデック
    "6645.T",  # オムロン
    "6701.T",  # NEC
    "6702.T",  # 富士通
    "6723.T",  # ルネサスエレクトロニクス
    "6724.T",  # セイコーエプソン
    "6752.T",  # パナソニックHD
    "6753.T",  # シャープ
    "6758.T",  # ソニーグループ
    "6762.T",  # TDK
    "6770.T",  # アルプスアルパイン
    "6841.T",  # 横河電機
    "6857.T",  # アドバンテスト
    "6861.T",  # キーエンス
    "6890.T",  # フェローテックホールディングス
    "6902.T",  # デンソー
    "6920.T",  # レーザーテック
    "6954.T",  # ファナック
    "6963.T",  # ローム
    "6971.T",  # 京セラ
    "6976.T",  # 太陽誘電
    "6981.T",  # 村田製作所
    "6988.T",  # 日東電工
    "7004.T",  # カナデビア
    "7011.T",  # 三菱重工業
    "7012.T",  # 川崎重工業
    "7013.T",  # ＩＨＩ
    "7186.T",  # コンコルディア・フィナンシャルグループ
    "7201.T",  # 日産自動車
    "7202.T",  # いすゞ自動車
    "7203.T",  # トヨタ自動車
    "7211.T",  # 三菱自動車工業
    "7261.T",  # マツダ
    "7267.T",  # ホンダ
    "7269.T",  # スズキ
    "7270.T",  # ＳＵＢＡＲＵ
    "7272.T",  # ヤマハ発動機
    "7453.T",  # 良品計画
    "7532.T",  # パン・パシフィック・インターナショナルホールディングス
    "7729.T",  # 東京精密
    "7731.T",  # ニコン
    "7733.T",  # オリンパス
    "7735.T",  # SCREENホールディングス
    "7741.T",  # ＨＯＹＡ
    "7751.T",  # キヤノン
    "7752.T",  # リコー
    "7832.T",  # バンダイナムコホールディングス
    "7911.T",  # ＴＯＰＰＡＮホールディングス
    "7912.T",  # 大日本印刷
    "7951.T",  # ヤマハ
    "7974.T",  # 任天堂
    "8001.T",  # 伊藤忠商事
    "8002.T",  # 丸紅
    "8015.T",  # 豊田通商
    "8031.T",  # 三井物産
    "8035.T",  # 東京エレクトロン
    "8053.T",  # 住友商事
    "8058.T",  # 三菱商事
    "8233.T",  # 高島屋
    "8252.T",  # 丸井グループ
    "8253.T",  # クレディセゾン
    "8267.T",  # イオン
    "8304.T",  # あおぞら銀行
    "8306.T",  # 三菱UFJフィナンシャル・グループ
    "8308.T",  # りそなホールディングス
    "8309.T",  # 三井住友トラストグループ
    "8316.T",  # 三井住友フィナンシャルグループ
    "8331.T",  # 千葉銀行
    "8354.T",  # ふくおかフィナンシャルグループ
    "8411.T",  # みずほフィナンシャルグループ
    "8591.T",  # オリックス
    "8601.T",  # 大和証券グループ本社
    "8604.T",  # 野村ホールディングス
    "8630.T",  # ＳＯＭＰＯホールディングス
    "8697.T",  # 日本取引所グループ
    "8725.T",  # ＭＳ＆ＡＤインシュアランスグループホールディングス
    "8750.T",  # 第一生命ホールディングス
    "8766.T",  # 東京海上HD
    "8795.T",  # Ｔ＆Ｄホールディングス
    "8801.T",  # 三井不動産
    "8802.T",  # 三菱地所
    "8804.T",  # 東京建物
    "8830.T",  # 住友不動産
    "9001.T",  # 東武鉄道
    "9005.T",  # 東急
    "9007.T",  # 小田急電鉄
    "9008.T",  # 京王電鉄
    "9009.T",  # 京成電鉄
    "9020.T",  # JR東日本
    "9021.T",  # 西日本旅客鉄道
    "9022.T",  # JR東海
    "9064.T",  # ヤマトホールディングス
    "9101.T",  # 日本郵船
    "9104.T",  # 商船三井
    "9107.T",  # 川崎汽船
    "9147.T",  # ＮＩＰＰＯＮ　ＥＸＰＲＥＳＳホールディングス
    "9201.T",  # 日本航空
    "9202.T",  # ＡＮＡホールディングス
    "9432.T",  # NTT
    "9433.T",  # KDDI
    "9434.T",  # ソフトバンク
    "9501.T",  # 東京電力ホールディングス
    "9502.T",  # 中部電力
    "9503.T",  # 関西電力
    "9531.T",  # 東京瓦斯
    "9532.T",  # 大阪瓦斯
    "9602.T",  # 東宝
    "9735.T",  # セコム
    "9766.T",  # コナミグループ
    "9843.T",  # ニトリHD
    "9983.T",  # ファーストリテイリング
    "9984.T",  # ソフトバンクグループ
]

UNIVERSE_NAMES: dict[str, str] = {
    "1332.T": "ニッスイ",
    "1605.T": "ＩＮＰＥＸ",
    "1721.T": "コムシスホールディングス",
    "1801.T": "大成建設",
    "1802.T": "大林組",
    "1803.T": "清水建設",
    "1808.T": "長谷工コーポレーション",
    "1812.T": "鹿島建設",
    "1925.T": "大和ハウス工業",
    "1928.T": "積水ハウス",
    "1963.T": "日揮ホールディングス",
    "2002.T": "日清製粉グループ本社",
    "2269.T": "明治ホールディングス",
    "2282.T": "日本ハム",
    "2413.T": "エムスリー",
    "2432.T": "ディー・エヌ・エー",
    "2501.T": "サッポロホールディングス",
    "2502.T": "アサヒグループホールディングス",
    "2503.T": "キリンホールディングス",
    "2768.T": "双日",
    "2801.T": "キッコーマン",
    "2802.T": "味の素",
    "285A.T": "キオクシアホールディングス",
    "2871.T": "ニチレイ",
    "2914.T": "JT",
    "3086.T": "Ｊ．フロント　リテイリング",
    "3092.T": "ＺＯＺＯ",
    "3099.T": "三越伊勢丹ホールディングス",
    "3289.T": "東急不動産ホールディングス",
    "3382.T": "セブン&アイ・ホールディングス",
    "3401.T": "帝人",
    "3402.T": "東レ",
    "3405.T": "クラレ",
    "3407.T": "旭化成",
    "3436.T": "SUMCO",
    "3659.T": "ネクソン",
    "3697.T": "ＳＨＩＦＴ",
    "3861.T": "王子ホールディングス",
    "4004.T": "レゾナック・ホールディングス",
    "4005.T": "住友化学",
    "4021.T": "日産化学",
    "4042.T": "東ソー",
    "4043.T": "トクヤマ",
    "4061.T": "デンカ",
    "4062.T": "イビデン",
    "4063.T": "信越化学工業",
    "4151.T": "協和キリン",
    "4183.T": "三井化学",
    "4188.T": "三菱ケミカルグループ",
    "4208.T": "ＵＢＥ",
    "4307.T": "野村総合研究所",
    "4324.T": "電通グループ",
    "4385.T": "メルカリ",
    "4452.T": "花王",
    "4502.T": "武田薬品工業",
    "4503.T": "アステラス製薬",
    "4506.T": "住友ファーマ",
    "4507.T": "塩野義製薬",
    "4519.T": "中外製薬",
    "4523.T": "エーザイ",
    "4543.T": "テルモ",
    "4568.T": "第一三共",
    "4578.T": "大塚ホールディングス",
    "4661.T": "オリエンタルランド",
    "4689.T": "ＬＩＮＥヤフー",
    "4704.T": "トレンドマイクロ",
    "4751.T": "サイバーエージェント",
    "4755.T": "楽天グループ",
    "4901.T": "富士フイルムHD",
    "4902.T": "コニカミノルタ",
    "4911.T": "資生堂",
    "5019.T": "出光興産",
    "5020.T": "ＥＮＥＯＳホールディングス",
    "5101.T": "横浜ゴム",
    "5108.T": "ブリヂストン",
    "5201.T": "ＡＧＣ",
    "5214.T": "日本電気硝子",
    "5233.T": "太平洋セメント",
    "5301.T": "東海カーボン",
    "5332.T": "ＴＯＴＯ",
    "5333.T": "日本碍子",
    "5401.T": "日本製鉄",
    "5406.T": "神戸製鋼所",
    "5411.T": "ＪＦＥホールディングス",
    "543A.T": "ARCHION",
    "5631.T": "日本製鋼所",
    "5706.T": "三井金属鉱業",
    "5711.T": "三菱マテリアル",
    "5713.T": "住友金属鉱山",
    "5714.T": "ＤＯＷＡホールディングス",
    "5801.T": "古河電気工業",
    "5802.T": "住友電気工業",
    "5803.T": "フジクラ",
    "5831.T": "しずおかフィナンシャルグループ",
    "6098.T": "リクルートHD",
    "6103.T": "オークマ",
    "6113.T": "アマダ",
    "6146.T": "ディスコ",
    "6178.T": "日本郵政",
    "6273.T": "SMC",
    "6301.T": "コマツ",
    "6302.T": "住友重機械工業",
    "6305.T": "日立建機",
    "6326.T": "クボタ",
    "6361.T": "荏原製作所",
    "6367.T": "ダイキン工業",
    "6471.T": "日本精工",
    "6472.T": "ＮＴＮ",
    "6473.T": "ジェイテクト",
    "6479.T": "ミネベアミツミ",
    "6501.T": "日立製作所",
    "6503.T": "三菱電機",
    "6504.T": "富士電機",
    "6506.T": "安川電機",
    "6526.T": "ソシオネクスト",
    "6532.T": "ベイカレント",
    "6594.T": "ニデック",
    "6645.T": "オムロン",
    "6701.T": "NEC",
    "6702.T": "富士通",
    "6723.T": "ルネサスエレクトロニクス",
    "6724.T": "セイコーエプソン",
    "6752.T": "パナソニックHD",
    "6753.T": "シャープ",
    "6758.T": "ソニーグループ",
    "6762.T": "TDK",
    "6770.T": "アルプスアルパイン",
    "6841.T": "横河電機",
    "6857.T": "アドバンテスト",
    "6861.T": "キーエンス",
    "6890.T": "フェローテックホールディングス",
    "6902.T": "デンソー",
    "6920.T": "レーザーテック",
    "6954.T": "ファナック",
    "6963.T": "ローム",
    "6971.T": "京セラ",
    "6976.T": "太陽誘電",
    "6981.T": "村田製作所",
    "6988.T": "日東電工",
    "7004.T": "カナデビア",
    "7011.T": "三菱重工業",
    "7012.T": "川崎重工業",
    "7013.T": "ＩＨＩ",
    "7186.T": "コンコルディア・フィナンシャルグループ",
    "7201.T": "日産自動車",
    "7202.T": "いすゞ自動車",
    "7203.T": "トヨタ自動車",
    "7211.T": "三菱自動車工業",
    "7261.T": "マツダ",
    "7267.T": "ホンダ",
    "7269.T": "スズキ",
    "7270.T": "ＳＵＢＡＲＵ",
    "7272.T": "ヤマハ発動機",
    "7453.T": "良品計画",
    "7532.T": "パン・パシフィック・インターナショナルホールディングス",
    "7729.T": "東京精密",
    "7731.T": "ニコン",
    "7733.T": "オリンパス",
    "7735.T": "SCREENホールディングス",
    "7741.T": "ＨＯＹＡ",
    "7751.T": "キヤノン",
    "7752.T": "リコー",
    "7832.T": "バンダイナムコホールディングス",
    "7911.T": "ＴＯＰＰＡＮホールディングス",
    "7912.T": "大日本印刷",
    "7951.T": "ヤマハ",
    "7974.T": "任天堂",
    "8001.T": "伊藤忠商事",
    "8002.T": "丸紅",
    "8015.T": "豊田通商",
    "8031.T": "三井物産",
    "8035.T": "東京エレクトロン",
    "8053.T": "住友商事",
    "8058.T": "三菱商事",
    "8233.T": "高島屋",
    "8252.T": "丸井グループ",
    "8253.T": "クレディセゾン",
    "8267.T": "イオン",
    "8304.T": "あおぞら銀行",
    "8306.T": "三菱UFJフィナンシャル・グループ",
    "8308.T": "りそなホールディングス",
    "8309.T": "三井住友トラストグループ",
    "8316.T": "三井住友フィナンシャルグループ",
    "8331.T": "千葉銀行",
    "8354.T": "ふくおかフィナンシャルグループ",
    "8411.T": "みずほフィナンシャルグループ",
    "8591.T": "オリックス",
    "8601.T": "大和証券グループ本社",
    "8604.T": "野村ホールディングス",
    "8630.T": "ＳＯＭＰＯホールディングス",
    "8697.T": "日本取引所グループ",
    "8725.T": "ＭＳ＆ＡＤインシュアランスグループホールディングス",
    "8750.T": "第一生命ホールディングス",
    "8766.T": "東京海上HD",
    "8795.T": "Ｔ＆Ｄホールディングス",
    "8801.T": "三井不動産",
    "8802.T": "三菱地所",
    "8804.T": "東京建物",
    "8830.T": "住友不動産",
    "9001.T": "東武鉄道",
    "9005.T": "東急",
    "9007.T": "小田急電鉄",
    "9008.T": "京王電鉄",
    "9009.T": "京成電鉄",
    "9020.T": "JR東日本",
    "9021.T": "西日本旅客鉄道",
    "9022.T": "JR東海",
    "9064.T": "ヤマトホールディングス",
    "9101.T": "日本郵船",
    "9104.T": "商船三井",
    "9107.T": "川崎汽船",
    "9147.T": "ＮＩＰＰＯＮ　ＥＸＰＲＥＳＳホールディングス",
    "9201.T": "日本航空",
    "9202.T": "ＡＮＡホールディングス",
    "9432.T": "NTT",
    "9433.T": "KDDI",
    "9434.T": "ソフトバンク",
    "9501.T": "東京電力ホールディングス",
    "9502.T": "中部電力",
    "9503.T": "関西電力",
    "9531.T": "東京瓦斯",
    "9532.T": "大阪瓦斯",
    "9602.T": "東宝",
    "9735.T": "セコム",
    "9766.T": "コナミグループ",
    "9843.T": "ニトリHD",
    "9983.T": "ファーストリテイリング",
    "9984.T": "ソフトバンクグループ",
}
```

補足: この228銘柄は、拡張前の既存60銘柄と、2026年7月時点の日経225構成銘柄225件（[日経平均プロフィル](https://indexes.nikkei.co.jp/nkave/index/component?idx=nk225)の構成銘柄一覧をもとに作成）の和集合。全225件中224件を`app/docs/data_j.xls`（2025年6月30日時点のJPX公式全銘柄一覧）に対して銘柄コード・銘柄名で突合検証済み。唯一未検証だった`543A`（ARCHION）は2026年4月1日新規上場（日野自動車と三菱ふそうの経営統合会社）のため`data_j.xls`のスナップショットより後の上場であり、社名は上場時のニュースで確認済み。

- [x] **Step 4: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_universe.py -v`
Expected: 6件すべてPASS

- [x] **Step 5: コミット**

```bash
cd app
git add screening/universe.py tests/test_universe.py
git commit -m "feat: UNIVERSEを日経225全銘柄と既存銘柄の和集合(228銘柄)に拡張"
```

---

### Task 2: fetch_universe_fundamentalsを並列化する

**Files:**
- Modify: `data_api/stock_price_api.py:76-105`（`fetch_universe_fundamentals`関数）
- Test: `tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `common.concurrency.map_concurrently(items: list, fn, max_workers: int = 8) -> dict`（既存、`app.py`の一括バックテストで使用中。例外を送出したitemの値はそのitemキーに対する`Exception`インスタンスとして格納される）
- Produces: `fetch_universe_fundamentals(tickers, cache_dir, fetch_fundamentals=fetch_fundamentals) -> pd.DataFrame`（シグネチャ・戻り値の列構成は変更しない。個別銘柄の取得失敗時はその銘柄を結果から除外する点のみ新規追加の挙動）

- [x] **Step 1: 失敗ケースの失敗するテストを書く**

`tests/test_stock_price_api.py` の末尾（既存の`test_fetch_universe_fundamentals_uses_cache_on_second_call`の後）に追記する:

```python
def test_fetch_universe_fundamentals_skips_ticker_that_raises_and_keeps_others(tmp_path):
    def fake_fetch_fundamentals(ticker_symbol):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    tickers = ["AAA.T", "BAD.T", "CCC.T"]
    df = stock_price_api.fetch_universe_fundamentals(
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert sorted(df["ticker"].tolist()) == ["AAA.T", "CCC.T"]
```

- [x] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_stock_price_api.py::test_fetch_universe_fundamentals_skips_ticker_that_raises_and_keeps_others -v`
Expected: FAIL（現状の実装は例外をそのまま送出するため、`ValueError: boom`で異常終了する）

- [x] **Step 3: `fetch_universe_fundamentals`を並列化し、例外を送出した銘柄をスキップするよう実装する**

`data_api/stock_price_api.py` の冒頭のimport群に以下を追加する:

```python
from common.concurrency import map_concurrently
```

`fetch_universe_fundamentals`関数（現在76-105行目）を以下に置き換える:

```python
def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    results = map_concurrently(tickers, fetch_fundamentals)
    rows = []
    for ticker_symbol in tickers:
        data = results[ticker_symbol]
        if isinstance(data, Exception):
            continue
        rows.append(
            {
                "ticker": data.get("ticker", ticker_symbol),
                "name": data.get("name"),
                "per": data.get("trailing_pe"),
                "pbr": data.get("price_to_book"),
                # yfinance's dividendYield is already a percentage number
                # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                "dividend_yield_pct": data.get("dividend_yield"),
                "market_cap": data.get("market_cap"),
            }
        )
    df = pd.DataFrame(rows)
    write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
```

- [x] **Step 4: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_stock_price_api.py -v`
Expected: 全件PASS（新規追加分を含む。既存の`test_fetch_universe_fundamentals_uses_cache_on_second_call`は`tickers`のリスト順で行を構築するロジックを維持しているため、並列化後もticker列の順序は変わらずPASSする）

- [x] **Step 5: 全体テストスイートを実行し、他への副作用がないことを確認する**

Run: `cd app && uv run pytest -v`
Expected: 全件PASS

- [x] **Step 6: コミット**

```bash
cd app
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "perf: fetch_universe_fundamentalsをmap_concurrentlyで並列化し失敗銘柄をスキップ"
```

---

### Task 3: UI動作の手動確認

**Files:** なし（コード変更なし、動作確認のみ）

**Interfaces:**
- Consumes: Task 1・Task 2で変更した`UNIVERSE`（228銘柄）と並列化済み`fetch_universe_fundamentals`
- Produces: なし（確認結果をこのタスクの完了条件とする）

- [x] **Step 1: アプリを起動する**

Run: `cd app && uv run python -m streamlit run app.py`
Expected: エラーなく起動し、ブラウザでアプリが開く

実施結果: `uv run python -m streamlit run app.py --server.headless true` で起動し、Playwright（Chromium）で実接続。エラーなく描画された（`console --errors`相当のpageerror/consoleエラー監視でも検出なし）。

- [x] **Step 2: スクリーニング用データ取得（`fetch_universe_fundamentals`）を実データで確認する**

ブラウザのスクリーニングタブはLLM（Claude Code CLI）による自然言語→フィルタ変換を経由するため、UI経由の確認に加えて、Task 2で変更した`fetch_universe_fundamentals`を実際の`UNIVERSE`（228銘柄）に対して直接実行し、実データでの挙動を確認した。

実施結果:
```
elapsed: 10.1s
rows: 228 / universe: 228
```
228銘柄全件が取得成功（スキップなし）。2026年4月上場の新規銘柄`543A.T`（ARCHION Corporation）も実データで正しく取得できることをキャッシュファイル（`data/cache/2026-07-20-universe-*.txt`）の内容で確認した。

- [x] **Step 3: 単一銘柄バックテストタブを確認する**

実装時に`app.py`を確認したところ、単一銘柄バックテストの銘柄コード入力は`UNIVERSE`を参照するセレクトボックスではなく自由入力の`st.text_input`（`backtest_ticker = st.text_input("銘柄コード", placeholder="7203.T", ...)`）だった。UNIVERSE拡張の影響を受けないため、本ステップで確認すべき変化はない（設計書もこの点を修正済み）。

- [x] **Step 4: 一括バックテストタブを実行する**

一括バックテストタブで「移動平均クロスオーバー」戦略・3y期間で「一括バックテストを実行」をクリックし、Playwrightで結果を待機した。

実施結果: エラーなく完了。「株価データを取得中...（231銘柄）」の表示で対象銘柄数がUNIVERSE(228) ∪ 保有銘柄（重複除く追加3銘柄）＝231件になっていることを確認。ランキング表・上位5銘柄のAIコメントとも正常に生成され、新規追加銘柄（`5801.T` 古河電気工業、`7013.T` IHI、`5803.T` フジクラ、`5706.T` 三井金属鉱業 等）が上位にランクインしていることを確認した。

- [x] **Step 5: ポートフォリオタブの銘柄名補完を確認する**

ポートフォリオタブの「銘柄を検索して追加」欄に「ニッスイ」と入力し、新規追加銘柄`1332.T ニッスイ`が候補に表示されることをスクリーンショットで確認した。

このタスクにチェックボックスの完了以外の成果物はない。すべて期待通り完了した。

---

## Global Constraintsの確認（実装完了時のチェックリスト）

- [x] `pyproject.toml`に`xlrd`等の新規依存が追加されていないこと
- [x] `UNIVERSE`が`list[str]`、`UNIVERSE_NAMES`が`dict[str, str]`のままであること
- [x] `tests/test_universe.py::test_universe_retains_all_pre_expansion_tickers`がPASSしていること
- [x] `common/cache.py`のキャッシュキー生成ロジック・ファイル形式に変更がないこと
