# 個別銘柄の詳細分析（ファンダメンタルズ・テクニカル・ニュース）を統合し、
# LLMに総合コメントを生成させるためのプロンプトを組み立てるモジュール。


def build_stock_detail_prompt(
    ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]
) -> str:
    # ニュースが無い場合でもプロンプトの体裁が崩れないよう、代替文言を用意する。
    news_titles = "\n".join(f"- {item.get('title')}" for item in news) or "- (ニュースなし)"
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
        f"テクニカルシグナル: {technical.get('signal')}\n"
        f"直近ニュース見出し:\n{news_titles}\n"
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
