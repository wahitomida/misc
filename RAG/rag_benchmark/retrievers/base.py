"""Retriever 共通基底 + データクラス."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..utils.llm_client import LLMClient
from ..utils.neo4j_client import Neo4jClient


@dataclass
class RetrievalResult:
    """Retriever の実行結果.

    pre_generated_answer が None でない場合、main.py は generate_answer をスキップし、
    この回答をそのまま採用する (Self-RAG など内部で生成 + 評価を行う手法用).
    """
    contexts: list[str]
    source_deal_ids: list[int]
    retrieval_time_ms: float
    context_token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    pre_generated_answer: str | None = None
    pre_gen_input_tokens: int = 0
    pre_gen_output_tokens: int = 0
    pre_gen_model: str = ""


@dataclass
class GenerationResult:
    """回答生成の結果."""
    answer: str
    generation_time_ms: float
    input_tokens: int
    output_tokens: int
    model: str


@dataclass
class BenchmarkResult:
    """1 クエリ × 1 手法の完全結果."""
    query_id: str
    query_text: str
    query_type: str
    method_id: str
    method_name: str
    retrieval: RetrievalResult
    generation: GenerationResult
    total_time_ms: float


class BaseRetriever(ABC):
    """全 Retriever の基底クラス."""

    def __init__(self, neo4j_client: Neo4jClient, llm_client: LLMClient, config: dict):
        self.neo4j = neo4j_client
        self.llm = llm_client
        self.config = config

    @abstractmethod
    def retrieve(self, query: str) -> RetrievalResult:
        """クエリに対してコンテキストを取得."""

    @property
    @abstractmethod
    def method_id(self) -> str:
        """手法 ID (R01〜R11)."""

    @property
    @abstractmethod
    def method_name(self) -> str:
        """手法名."""
