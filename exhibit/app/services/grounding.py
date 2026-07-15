# -*- coding: utf-8 -*-
"""Vertex AI Google検索グラウンディング呼び出し"""

from __future__ import annotations
import json
import re
import asyncio
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from vertexai.generative_models import (
    GenerationConfig,
    GenerativeModel,
    Tool,
    grounding,
)

from app.config import settings

logger = logging.getLogger("exhibit.grounding")
logger.setLevel(logging.INFO)

_executor = ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_SEARCHES)


def _get_model() -> GenerativeModel:
    """Google検索グラウンディング付きモデルを取得（generation_configは呼び出し時に渡す）"""
    try:
        search_tool = Tool.from_dict({"google_search": {}})
    except Exception:
        search_tool = Tool.from_google_search_retrieval(
            grounding.GoogleSearchRetrieval()
        )

    return GenerativeModel(
        model_name=settings.MODEL_NAME,
        tools=[search_tool],
    )


def _extract_metadata(response) -> tuple[list[dict], list[str]]:
    """レスポンスからソースURLと検索クエリを抽出

    返り値:
        sources: [{title, url}] グラウンディング済みの実在URLリスト
        queries: 実際に使われた検索クエリ
    """
    sources = []
    queries = []
    seen_urls = set()
    try:
        candidate = response.candidates[0]
        metadata = getattr(candidate, "grounding_metadata", None)
        if metadata:
            if hasattr(metadata, "grounding_chunks") and metadata.grounding_chunks:
                for chunk in metadata.grounding_chunks:
                    web = getattr(chunk, "web", None)
                    if web:
                        url = getattr(web, "uri", "") or ""
                        title = getattr(web, "title", "") or ""
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            sources.append({"title": title, "url": url})
            if hasattr(metadata, "web_search_queries") and metadata.web_search_queries:
                queries = list(metadata.web_search_queries)
    except Exception:
        pass
    return sources, queries


def _call_gemini_sync(prompt: str, max_output_tokens: int = 5000) -> tuple[str, list[dict], list[str]]:
    """同期でGemini APIを呼び出し（バックアップ版と同じパターン）"""
    model = _get_model()
    generation_config = GenerationConfig(
        temperature=1.0,
        max_output_tokens=max_output_tokens,
    )
    response = model.generate_content(
        prompt,
        generation_config=generation_config,
    )
    text = response.text if response.text else ""
    sources, queries = _extract_metadata(response)
    return text, sources, queries


async def call_gemini(prompt: str, max_output_tokens: int = 5000) -> tuple[str, list[dict], list[str]]:
    """非同期でGemini APIを呼び出し（スレッドプールで実行）"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _call_gemini_sync, prompt, max_output_tokens)


async def call_gemini_json(prompt: str, max_output_tokens: int = 5000) -> tuple[Optional[dict], list[dict], list[str]]:
    """Gemini APIを呼び出しJSON応答をパース"""
    text, sources, queries = await call_gemini(prompt, max_output_tokens=max_output_tokens)
    logger.info(f"[Gemini] response length={len(text)}, sources={len(sources)}, queries={len(queries)}")
    if queries:
        logger.info(f"[Gemini] search queries: {queries[:5]}")
    parsed = _extract_json(text)
    if parsed is None:
        logger.warning(f"[Gemini] JSON parse failed. First 1000 chars:\n{text[:1000]}")
        parsed = {"raw_text": text}
    return parsed, sources, queries


def _extract_json(text: str) -> Optional[dict]:
    """レスポンスからJSON部分を抽出してパース"""
    if not text:
        return None
    # 1. ```json ... ``` を探す
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2. 最初の { から最後の } までを抽出
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # 3. そのままパースを試みる
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None
