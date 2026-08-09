# テクニカル分析エージェント

## この教材で身につくこと

- pandasで移動平均線・RSI・ATR・ADX・OBVなどのテクニカル指標を計算する方法
- テクニカル指標を「トレンド系・オシレーター系・ボラティリティ系・出来高系」に
  体系立てて整理し、指標同士の役割の重複を避けて選ぶ考え方
- 計算済みの数値をLLMに渡し、解釈・説明させる設計パターン
- LLMに直接数値計算をさせてはいけない理由

## 概要

テクニカル分析エージェントは、価格データから指標を計算し、
その結果をLLMに解釈させるプログラムです。
指標の計算は必ずPython側（pandas）で行い、LLMには計算済みの
数値の意味を説明させる役割だけを与えます。

## 位置づけ

[03-data-api/01-stock-price-api.md](../03-data-api/01-stock-price-api.md) で
学んだyfinanceの価格取得を土台にします。
LLMへの説明生成には [03-data-api/02-llm-api-integration.md](../03-data-api/02-llm-api-integration.md)
の `call_llm` を使用します。

## 主要概念・パラメータ解説

### なぜLLMに計算させないのか

LLMはトークン単位でテキストを生成するモデルであり、
桁数の多い数値の四則演算や統計計算を苦手とします。
移動平均やRSIのような指標は、Python側で正確に計算し、
LLMには「計算結果の解釈」のみを担当させます。

### テクニカル指標の体系

テクニカル指標は「何を測るか」で4つのカテゴリーに整理できます。
同じカテゴリーの指標は役割が重なりやすいため、闇雲に数を増やすのではなく、
各カテゴリーから代表的な指標を1つずつ選ぶと、指標同士が補い合う
バランスの良い構成になります。

| カテゴリー | 何を測るか | 代表的な指標 | 本教材での扱い |
|---|---|---|---|
| トレンド系 | 方向性・強さ | 移動平均クロス、ADX、MACD | 移動平均クロス・ADXを実装 |
| オシレーター系 | 買われすぎ／売られすぎ（勢い） | RSI、ストキャスティクス | RSIを実装 |
| ボラティリティ系 | 値動きの荒さ | ATR、ボリンジャーバンド | ATRを実装 |
| 出来高系 | 売買の勢いの裏付け | OBV、出来高移動平均 | OBVを実装 |

移動平均クロス（方向）→ ADX（その方向の強さ）→ RSI（勢いの過熱感）→
ATR（リスク管理のための値動きの大きさ）→ OBV（出来高による裏付け）、
という順で見ていくと、1銘柄のテクニカル状況を一貫したストーリーとして
説明できます。

### ゴールデンクロス/デッドクロス判定

| 用語 | 意味 |
|------|------|
| 短期移動平均線 | 直近N日の終値の単純移動平均（例: 25日） |
| 長期移動平均線 | 直近M日の終値の単純移動平均（例: 75日） |
| ゴールデンクロス | 短期線が長期線を下から上に抜けること |
| デッドクロス | 短期線が長期線を上から下に抜けること |

### compute_ma_crossover関数の入出力

| 項目 | 型 | 内容 |
|------|-----|------|
| 引数 `ticker` | `str` | 対象銘柄のティッカーシンボル |
| 引数 `short_window` | `int` | 短期移動平均の日数（既定25） |
| 引数 `long_window` | `int` | 長期移動平均の日数（既定75） |
| 戻り値 `ma_short` / `ma_long` | `float` | 直近の移動平均値 |
| 戻り値 `golden_cross` / `dead_cross` | `bool` | クロス発生の有無 |

### RSI（相対力指数、オシレーター系）

直近N日（通常14日）の値動きのうち、上昇分と下落分の比率から
「買われすぎ／売られすぎ」を判定する指標です。0〜100の値をとります。

- 平均上昇幅・平均下落幅をWilderの指数平滑（`alpha = 1 / period`）で計算
- `RSI = 100 - 100 / (1 + 平均上昇幅 / 平均下落幅)`
- 70以上: 買われすぎ、30以下: 売られすぎ

### ATR（Average True Range、平均真の値幅、ボラティリティ系）

値動きの「大きさ」を測る指標です。方向は判定しません。

- True Range = 「当日高値-当日安値」「\|当日高値-前日終値\|」
  「\|当日安値-前日終値\|」のうち最大値（ギャップも考慮する）
- ATR = True RangeをN日（通常14日）でWilderの指数平滑した値
- 終値に対する比率（ATR%）にすると銘柄間で比較しやすい
  （目安: 3%以上で高ボラティリティ、1%未満で低ボラティリティ）

### ADX（Average Directional Index、平均方向性指数、トレンド系）

トレンドの「強さ」を測る指標です（0〜100）。方向は+DI/-DIで別途判定します。

- 上昇の勢い（+DM）・下降の勢い（-DM）をTrue Rangeに対する比率
  （+DI・-DI）として算出し、その差をWilderの指数平滑したものがADX
- 25以上: 強いトレンド、20未満: レンジ相場（トレンドフォロー戦略が
  機能しにくい）

### OBV（On Balance Volume、出来高系）

値上がり日は出来高を加算、値下がり日は出来高を減算して累積した指標です。
価格の動きが出来高に裏付けられているかを確認するのに使います。

- 終値が前日比で上昇: `OBV += 出来高`、下落: `OBV -= 出来高`、変わらず: 据え置き
- 直近のOBVが一定期間前のOBVより高ければ「増加傾向」（出来高の裏付けあり）

## 実ソースコード

### 指標の計算（Python/pandas）

```python
import pandas as pd
import yfinance as yf


def compute_ma_crossover(
    ticker: str, short_window: int = 25, long_window: int = 75
) -> dict:
    hist = yf.Ticker(ticker).history(period="6mo")
    hist["ma_short"] = hist["Close"].rolling(short_window).mean()
    hist["ma_long"] = hist["Close"].rolling(long_window).mean()

    latest, prev = hist.iloc[-1], hist.iloc[-2]
    golden_cross = (
        prev["ma_short"] <= prev["ma_long"]
        and latest["ma_short"] > latest["ma_long"]
    )
    dead_cross = (
        prev["ma_short"] >= prev["ma_long"]
        and latest["ma_short"] < latest["ma_long"]
    )

    return {
        "ticker": ticker,
        "ma_short": round(float(latest["ma_short"]), 2),
        "ma_long": round(float(latest["ma_long"]), 2),
        "golden_cross": bool(golden_cross),
        "dead_cross": bool(dead_cross),
    }
```

### 計算結果をLLMに解釈させる

```python
from llm_client import call_llm  # 03-llm-api-integrationで定義


def explain_technical_signal(signal: dict) -> str:
    prompt = f"""
以下は既にPythonで正確に計算済みの移動平均線データです。
数値の再計算は不要です。この結果が示す意味を、
投資初心者にも分かるよう平易な言葉で説明してください。
断定的な売買判断は避け、あくまで指標の解釈として説明してください。

{signal}
"""
    return call_llm(prompt)
```

### 実行結果例

```python
signal = compute_ma_crossover("7203.T")
explanation = explain_technical_signal(signal)
```

```json
{
  "ticker": "7203.T",
  "ma_short": 2951.4,
  "ma_long": 2887.1,
  "golden_cross": true,
  "dead_cross": false
}
```

```text
25日移動平均線（2951.4円）が75日移動平均線（2887.1円）を
上抜けし、ゴールデンクロスが発生しています。
一般的に短期的な上昇トレンドへの転換を示すサインとされますが、
出来高や他の指標と合わせて確認することが望まれます。
```

### 実際のアプリでの実装

> 上記の`compute_ma_crossover`は概念理解のための最小実装です。
> RSI・ATR・ADX・OBVを含む完全な実装は
> [`app/analysis_agents/technical_agent.py`](../../app/analysis_agents/technical_agent.py)の
> `analyze_technical()`を参照してください。Wilderの指数平滑（`ewm(alpha=1/period)`）を
> RSI・ATR・ADXで共通の`_wilder_smooth()`ヘルパーとして再利用している点、
> データ不足時は例外を投げず`None`＋「データ不足」シグナルを返す設計（既存の
> 移動平均クロス判定と同じ方針）に注目してください。

```python
def analyze_technical(
    price_history: pd.DataFrame,
    short_window: int = 25,
    long_window: int = 75,
    rsi_period: int = 14,
    atr_period: int = 14,
    adx_period: int = 14,
    obv_period: int = 20,
) -> dict:
    close = price_history["Close"]

    result = _moving_average_signal(close, short_window, long_window)
    result.update(_rsi(close, rsi_period))
    result.update(_atr(price_history, atr_period))
    result.update(_adx(price_history, adx_period))
    result.update(_obv(price_history, obv_period))
    return result
```

計算結果は[個別銘柄の詳細画面](../06-real-world-examples/00-README.md)で
メトリクス表示され、AIの総合分析コメント生成プロンプト
（`app/prompt_patterns/stock_detail.py`の`build_stock_detail_prompt`）にも
「RSI: 72.5（買われすぎ）」のように解釈用の文脈として渡されます。

### 良い例 / 悪い例

```text
悪い例:
「直近25日の終値[2940, 2955, ...]からRSIを計算し、
買われすぎか判定してください」
→ LLMが生の数値列から統計計算を行うため、
  誤差や計算ミスが発生しやすい
```

```text
良い例:
「pandasで計算したRSI値は58.3です。この数値が
何を意味するか説明してください」
→ 計算はPython側で正確に行い、LLMは解釈のみを担当する
```

## 演習課題

1. `compute_ma_crossover` を参考に、RSI（相対力指数）を
   `pandas` で計算する関数 `compute_rsi(ticker, period=14)` を書け。
   書けたら[`app/analysis_agents/technical_agent.py`](../../app/analysis_agents/technical_agent.py)の
   `_rsi`と実装方針を比較せよ（Wilderの指数平滑を使っているか、
   平均下落幅が0のときにゼロ除算を避けているか）
2. 同様にATR（`compute_atr`）またはOBV（`compute_obv`）のどちらかを
   自分で実装せよ。ADXより計算がシンプルなため着手しやすい
3. `explain_technical_signal` のプロンプトに、RSI・ADX・ATRの
   計算結果も渡して複合的な説明を生成させよ
4. ゴールデンクロス・デッドクロスのどちらでもない場合の
   説明文が不自然にならないよう、プロンプトを調整せよ
5. （発展）ADXが低い（レンジ相場）銘柄では移動平均クロス戦略の
   説明のトーンを弱める、といった指標間の組み合わせルールを
   プロンプトに組み込んでみよ

## 理解度チェック

- [ ] LLMに直接テクニカル指標を計算させてはいけない理由を
      説明できる
- [ ] ゴールデンクロス・デッドクロスの判定条件を説明できる
- [ ] 計算結果とLLMの解釈を分離する設計のメリットを説明できる
- [ ] テクニカル指標を「トレンド系・オシレーター系・ボラティリティ系・
      出来高系」の4カテゴリーに分類できる
- [ ] RSIが「勢い」、ADXが「トレンドの強さ」、ATRが「値動きの大きさ」、
      OBVが「出来高による裏付け」を表すことを説明できる
- [ ] RSI・ATR・ADXの計算で共通して使われるWilderの指数平滑の考え方を
      説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: ファンダメンタル分析エージェント](01-fundamental-analysis-agent.md) | [次へ: ニュースリサーチエージェント →](03-news-research-agent.md)
