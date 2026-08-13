"""LLM呼び出しごとに、入力した事実情報（facts）とLLMの応答（ai_output）を
db.models.AiSession/AiGenerationへ分離して記録する共通ロガー。

同一session_idへの初回呼び出し時にai_sessions行を作成し、以降の呼び出しは
既存のセッションにai_generations行を積み増していく。"""
import json

from db.engine import SessionLocal
from db.models import AiGeneration, AiSession


def log_ai_generation(
    session_id: str,
    feature: str,
    facts: dict,
    prompt: str,
    ai_output: str,
    *,
    turn_index: int = 0,
    ticker: str | None = None,
    user_id: int | None = None,
    session_feature: str | None = None,
    session_factory=SessionLocal,
) -> None:
    with session_factory() as session:
        if session.get(AiSession, session_id) is None:
            session.add(
                AiSession(
                    id=session_id,
                    feature=session_feature or feature,
                    ticker=ticker,
                    user_id=user_id,
                )
            )
            # AiSessionとAiGenerationの間にORMのrelationship()を定義していないため、
            # session.commit()時の自動依存関係ソートに頼れない。ここで明示的にflushし、
            # ai_sessions行を先にINSERTしてFK制約違反を防ぐ。
            session.flush()
        session.add(
            AiGeneration(
                session_id=session_id,
                turn_index=turn_index,
                feature=feature,
                facts=json.dumps(facts, ensure_ascii=False, default=str),
                prompt=prompt,
                ai_output=ai_output,
            )
        )
        session.commit()
