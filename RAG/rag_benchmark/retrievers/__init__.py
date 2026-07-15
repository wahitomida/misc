"""Retriever Registry. 全 13 手法を一括登録."""
from __future__ import annotations

from .base import BaseRetriever, BenchmarkResult, GenerationResult, RetrievalResult
from .r01_naive_vector import NaiveVectorRetriever
from .r02_vector_reranker import VectorRerankerRetriever
from .r03_hyde import HyDERetriever
from .r04_graphrag_local import GraphRAGLocalRetriever
from .r05_graphrag_global import GraphRAGGlobalRetriever
from .r06_lightrag_hybrid import LightRAGHybridRetriever
from .r07_contextual_retrieval import ContextualRetrievalRetriever
from .r08_agentic_rag import AgenticRAGRetriever
from .r09_raptor import RaptorRetriever
from .r10_self_rag import SelfRAGRetriever
from .r11_corrective_rag import CorrectiveRAGRetriever
from .r12_rag_fusion import RAGFusionRetriever
from .r13_adaptive_ensemble import AdaptiveEnsembleRetriever

RETRIEVER_REGISTRY: dict[str, type[BaseRetriever]] = {
    "R01": NaiveVectorRetriever,
    "R02": VectorRerankerRetriever,
    "R03": HyDERetriever,
    "R04": GraphRAGLocalRetriever,
    "R05": GraphRAGGlobalRetriever,
    "R06": LightRAGHybridRetriever,
    "R07": ContextualRetrievalRetriever,
    "R08": AgenticRAGRetriever,
    "R09": RaptorRetriever,
    "R10": SelfRAGRetriever,
    "R11": CorrectiveRAGRetriever,
    "R12": RAGFusionRetriever,
    "R13": AdaptiveEnsembleRetriever,
}

__all__ = [
    "BaseRetriever",
    "BenchmarkResult",
    "GenerationResult",
    "RetrievalResult",
    "RETRIEVER_REGISTRY",
]
