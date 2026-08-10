# 自由記述の投資質問をカテゴリに分類し（Routingパターン）、カテゴリ別の
# 事実データを埋め込んだ回答プロンプトを組み立てるモジュール。
# 実際のデータ取得・カテゴリ分岐の実行はapp_tabs/qa_tab.pyが担う。
import json

from data_api.llm_client import call_llm as default_call_llm

_CATEGORIES = ["fundamental", "technical", "news", "portfolio", "general"]


def build_classify_prompt(question: str) -> str:
    return (
        "次の株式投資に関する質問を、fundamental, technical, news, portfolio, "
        "general のいずれか1つに分類し、分類名のみを出力してください"
        "（説明文やコードブロック記法は不要です）。\n\n"
        "- fundamental: PER・PBR・配当利回りなど個別銘柄の財務指標に関する質問\n"
        "- technical: 移動平均線など個別銘柄の値動き・チャートに関する質問\n"
        "- news: 個別銘柄の直近ニュース・センチメントに関する質問\n"
        "- portfolio: 保有銘柄全体の構成比・リスク・分散に関する質問\n"
        "- general: 上記のいずれにも当てはまらない一般的な投資知識の質問\n\n"
        f"質問: {question}"
    )


def classify_question(question: str, call_llm=default_call_llm) -> str:
    # 未知のラベルや空応答は安全側の "general" にフォールバックする。
    label = call_llm(build_classify_prompt(question)).strip()
    return label if label in _CATEGORIES else "general"


def build_fundamental_answer_prompt(question: str, fundamentals: dict) -> str:
    facts_json = json.dumps(fundamentals, ensure_ascii=False)
    return (
        "以下は対象銘柄のファンダメンタルズ指標です"
        "（Python側で取得済みのため再計算は不要です）。\n\n"
        f"{facts_json}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_technical_answer_prompt(question: str, technical: dict) -> str:
    facts_json = json.dumps(technical, ensure_ascii=False)
    return (
        "以下は対象銘柄のテクニカル分析結果（移動平均クロスオーバー）です"
        "（Python側で計算済みのため再計算は不要です）。\n\n"
        f"{facts_json}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def _format_news_lines(news: list[dict]) -> str:
    formatted = []
    for item in news:
        line = f"- {item['title']}"
        summary = item.get("summary")
        if summary:
            line += f"\n  要約: {summary}"
        formatted.append(line)
    return "\n".join(formatted) or "- (ニュースなし)"


def build_news_answer_prompt(question: str, news: list[dict]) -> str:
    lines = _format_news_lines(news)
    return (
        "以下は対象銘柄の直近ニュース見出しです"
        "（Python側で取得済みのため再取得は不要です）。\n\n"
        f"{lines}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_portfolio_answer_prompt(question: str, composition: dict, risk: dict) -> str:
    facts_json = json.dumps(
        {"composition": composition, "risk": risk}, ensure_ascii=False, default=str
    )
    return (
        "以下は保有ポートフォリオ全体の構成比・リスク指標です"
        "（Python側で計算済みのため再計算は不要です）。\n\n"
        f"{facts_json}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_general_answer_prompt(question: str) -> str:
    return (
        "次の株式投資に関する一般的な質問に、日本語で分かりやすく答えてください。"
        "個別銘柄への断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )
