# 個別銘柄の詳細分析（ファンダメンタルズ・テクニカル・ニュース）を統合し、
# LLMに総合コメントを生成させるためのプロンプトを組み立てるモジュール。


def _format_news_lines(news: list[dict]) -> str:
    # 見出しに続けて要約（あれば）を1行付記する。要約が無い記事は見出しのみ。
    # ニュースが無い場合でもプロンプトの体裁が崩れないよう、代替文言を用意する。
    lines = []
    for item in news:
        line = f"- {item.get('title')}"
        summary = item.get("summary")
        if summary:
            line += f"\n  要約: {summary}"
        lines.append(line)
    return "\n".join(lines) or "- (ニュースなし)"


def build_stock_detail_prompt(
    ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]
) -> str:
    news_lines = _format_news_lines(news)
    label = f"{ticker}（{name}）" if name else ticker
    # ファンダメンタルズ・テクニカル・ニュースの3系統の情報を1つのプロンプトにまとめ、
    # LLMが横断的に総合判断できるようにする。
    return (
        f"銘柄 {label} について、以下のファンダメンタルズ・テクニカル・ニュース見出しを踏まえて、"
        "投資家向けの総合分析コメントを日本語で3〜4文程度で作成してください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"PER: {fundamentals.get('per')}\n"
        f"PBR: {fundamentals.get('pbr')}\n"
        f"配当利回り: {fundamentals.get('dividend_yield')}\n"
        f"テクニカルシグナル（移動平均線）: {technical.get('signal')}\n"
        f"RSI(14日、勢い): {technical.get('rsi')}（{technical.get('rsi_signal') or '不明'}）\n"
        f"ADX(14日、トレンドの強さ): {technical.get('adx')}（{technical.get('adx_signal') or '不明'}）\n"
        f"ATR(14日、値動きの大きさ、値幅%): {technical.get('atr_pct')}%"
        f"（{technical.get('atr_signal') or '不明'}）\n"
        f"OBV(出来高、値動きの裏付け): {technical.get('obv_signal') or '不明'}\n"
        f"直近ニュース見出し:\n{news_lines}\n"
    )


def build_company_profile_prompt(
    ticker: str,
    name: str | None,
    sector: str | None,
    industry: str | None,
    business_summary: str,
) -> str:
    # yfinance由来の事業内容説明（英語）を根拠に、市場での立ち位置・強みを
    # 日本語で要約させる。business_summaryが空の場合はこの関数を呼ばない
    # （呼び出し元でガードする）。
    label = f"{ticker}（{name}）" if name else ticker
    return (
        f"銘柄 {label} について、以下の事業内容の説明を踏まえて、"
        "市場での立ち位置や強みを日本語で3〜4文程度で要約してください。"
        "断定的な投資判断は含めないでください。\n\n"
        f"業種: {sector or '不明'}\n"
        f"詳細業種: {industry or '不明'}\n"
        f"事業内容: {business_summary}\n"
    )


def build_news_summary_translation_prompt(summaries: list[str]) -> str:
    # 画面表示専用の日本語訳を1回のLLM呼び出しでまとめて生成するためのプロンプト。
    # 区切り文字@@@で入力と同じ順序・同じ件数の翻訳文を返すよう厳密に指示する
    # （呼び出し元が応答を分割して各記事に割り当てるため、件数のズレは致命的）。
    separator = "@@@"
    joined = f"\n{separator}\n".join(summaries)
    return (
        "以下は英文のニュース要約です。各要約を日本語に翻訳してください。\n"
        f"翻訳文の間は区切り文字「{separator}」だけの行を挟み、"
        "入力と同じ順序・同じ件数で出力してください。"
        "翻訳文以外の説明や前置きは出力しないでください。\n\n"
        f"{joined}"
    )
