"""OpenAI / Azure OpenAI Embedding API で Deal.content を埋め込み、Neo4j に書き戻す.

注意点:
  - すでに embedding が入っている Deal はスキップ
  - バッチ呼び出し + 指数バックオフ
  - 失敗した deal_id は最終リストで返す
  - Azure OpenAI が設定されていればそちらを優先 (config.use_azure_openai)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase
from tqdm import tqdm

from .config import (
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MAX_TOKENS,
    EMBEDDING_MODEL,
    use_azure_openai,
)

logger = logging.getLogger(__name__)


# 取得クエリ: embedding 未投入の Deal だけ取得
_FETCH_QUERY = """
MATCH (d:Deal)
WHERE d.embedding IS NULL AND d.content IS NOT NULL AND d.content <> ''
RETURN d.deal_id AS deal_id, d.content AS content
ORDER BY d.deal_id
"""

# 書き戻しクエリ
_WRITE_QUERY = """
UNWIND $batch AS row
MATCH (d:Deal {deal_id: row.deal_id})
CALL db.create.setNodeVectorProperty(d, 'embedding', row.embedding)
"""

# Neo4j 5.13+ で db.create.setNodeVectorProperty が無い場合のフォールバック (5.18+ では SET でも可)
_WRITE_QUERY_FALLBACK = """
UNWIND $batch AS row
MATCH (d:Deal {deal_id: row.deal_id})
SET d.embedding = row.embedding
"""


def _truncate_content(text: str, max_chars: int) -> str:
    """API 入力サイズを単純に文字数で切り詰める (token 数の安全側)."""
    if not text:
        return ""
    # max_tokens 8191 * 約2文字/token 程度を上限に
    limit = max_chars * 2
    if len(text) > limit:
        return text[:limit]
    return text


def _embed_with_backoff(
    client,
    model_or_deployment: str,
    inputs: List[str],
    max_retries: int = 6,
    initial_wait: float = 2.0,
) -> List[List[float]]:
    """OpenAI / Azure OpenAI Embedding API を指数バックオフ付きで呼び出す.

    Azure OpenAI でも openai SDK の embeddings.create(model=deployment_name) で同じインターフェース.
    """
    wait = initial_wait
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.embeddings.create(model=model_or_deployment, input=inputs)
            return [item.embedding for item in resp.data]
        except Exception as e:  # noqa: BLE001 - API 例外を集約
            last_err = e
            logger.warning("Embedding API 失敗 (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt == max_retries:
                break
            time.sleep(wait)
            wait *= 2
    raise RuntimeError(f"Embedding API 連続失敗 ({max_retries}回): {last_err}") from last_err


def _build_client_and_model(
    openai_api_key: str,
    model: str,
) -> tuple[Any, str, str]:
    """(client, model_or_deployment, backend_name) を返す."""
    if use_azure_openai():
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise ImportError("openai パッケージが必要です: pip install openai>=1.0") from e
        client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        # Azure では「モデル名」ではなく「デプロイメント名」を指定する
        deployment = AZURE_OPENAI_EMBED_DEPLOYMENT
        return client, deployment, "azure"

    if not openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY が未設定です (Azure を使う場合は AZURE_OPENAI_ENDPOINT/KEY を設定)"
        )
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("openai パッケージが必要です: pip install openai>=1.0") from e
    client = OpenAI(api_key=openai_api_key)
    return client, model, "openai"


def generate_embeddings(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    openai_api_key: str,
    database: str = "neo4j",
    model: str = EMBEDDING_MODEL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    max_tokens: int = EMBEDDING_MAX_TOKENS,
) -> Dict[str, Any]:
    """全 Deal.content を embedding 化して Neo4j に書き戻す.

    Returns
    -------
    dict
        {"processed": 投入件数, "skipped": スキップ件数, "failed": [失敗 deal_id, ...],
         "backend": "azure" or "openai", "model": 実際に使ったモデル/デプロイ名}
    """
    client, model_or_dep, backend = _build_client_and_model(openai_api_key, model)

    processed = 0
    failed: List[int] = []
    skipped = 0

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        # 1) 未投入 Deal を取得
        with driver.session(database=database) as session:
            rows = list(session.run(_FETCH_QUERY))
        total = len(rows)
        if total == 0:
            logger.info("embedding 対象 Deal なし (全件投入済み)")
            return {
                "processed": 0, "skipped": 0, "failed": [],
                "backend": backend, "model": model_or_dep,
            }

        logger.info(
            "embedding 開始: 対象 %d 件 backend=%s model/deployment=%s batch=%d dim=%d",
            total, backend, model_or_dep, batch_size, EMBEDDING_DIMENSIONS,
        )

        # 2) バッチ単位で API 呼び出し → 書き戻し
        with driver.session(database=database) as session:
            for i in tqdm(range(0, total, batch_size), desc="Embedding", leave=False):
                chunk = rows[i : i + batch_size]
                inputs: List[str] = []
                ids: List[int] = []
                for r in chunk:
                    text = _truncate_content(r["content"] or "", max_tokens)
                    if not text:
                        skipped += 1
                        continue
                    inputs.append(text)
                    ids.append(int(r["deal_id"]))
                if not inputs:
                    continue
                try:
                    vectors = _embed_with_backoff(client, model_or_dep, inputs)
                except RuntimeError as e:
                    logger.error("バッチ %d-%d が失敗: %s", i, i + len(chunk), e)
                    failed.extend(ids)
                    continue
                batch = [
                    {"deal_id": did, "embedding": vec}
                    for did, vec in zip(ids, vectors)
                ]
                # 5.18+ なら SET でも可、5.13-5.17 では db.create.setNodeVectorProperty
                try:
                    session.execute_write(lambda tx: tx.run(_WRITE_QUERY, batch=batch))
                except Exception as e:  # noqa: BLE001
                    logger.warning("setNodeVectorProperty が使えないため SET で書き戻し: %s", e)
                    session.execute_write(lambda tx: tx.run(_WRITE_QUERY_FALLBACK, batch=batch))
                processed += len(batch)
    finally:
        driver.close()

    logger.info(
        "embedding 完了: processed=%d skipped=%d failed=%d backend=%s",
        processed, skipped, len(failed), backend,
    )
    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "backend": backend,
        "model": model_or_dep,
    }
