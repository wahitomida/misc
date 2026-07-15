"""コンテキスト → LLM → 回答."""
from __future__ import annotations

import time

from ..retrievers.base import GenerationResult
from ..utils.llm_client import LLMClient

GENERATION_SYSTEM_PROMPT = """
あなたはセンサ商談の専門家です。
提供されたコンテキスト情報のみを根拠に、質問に対して正確かつ具体的に回答してください。
コンテキストに含まれない情報は「情報が不足しています」と明示してください。
回答は日本語で、以下の構造で記述してください:
1. 結論（1-2文）
2. 根拠（箇条書き、コンテキストから引用）
3. 補足事項（あれば）
""".strip()


def generate_answer(
    llm: LLMClient,
    query: str,
    contexts: list[str],
    temperature: float = 0.2,
) -> GenerationResult:
    """contexts を結合して LLM に渡し、回答を生成."""
    joined = "\n\n---\n\n".join(contexts) if contexts else "(コンテキストなし)"
    user_prompt = f"""【質問】
{query}

【コンテキスト】
{joined}

【回答】"""
    t0 = time.perf_counter()
    chat = llm.chat(GENERATION_SYSTEM_PROMPT, user_prompt, temperature=temperature)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return GenerationResult(
        answer=chat.text,
        generation_time_ms=elapsed_ms,
        input_tokens=chat.input_tokens,
        output_tokens=chat.output_tokens,
        model=chat.model,
    )
