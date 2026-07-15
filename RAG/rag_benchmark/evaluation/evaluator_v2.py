"""RAGAS 準拠の RAG 評価器 (v2).

v1 (`evaluator.py`) は 5 軸を一括採点する単段評価で、Retrieval と Generation の
切り分けができなかった. v2 は以下の 3 段階に分離する.

  1. Retrieval 評価   (コンテキストのみを見る)
       - context_precision  : 取得コンテキスト中の関連割合
       - context_recall     : 必要情報の被覆度
       - context_relevancy  : 全体としての質問適合度

  2. Generation 評価  (コンテキスト + 回答を見る)
       - faithfulness         : 回答主張のコンテキスト裏付け度
       - answer_relevancy     : 回答の質問適合度
       - answer_completeness  : 期待観点の網羅度

  3. Hallucination 検出 (任意・コスト削減のため skip 可能)
       - 回答の各主張を supported / partially_supported / not_supported に分類
       - hallucination_rate = not_supported の割合

総合スコア:
  composite_score = (0.4 * retrieval_score + 0.5 * generation_score
                     + 0.1 * keyword_coverage) * 100

speed (latency) は composite に含めず、ランキング上は別表示にする.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..utils.llm_client import LLMClient
from ..utils.synonym_dict import CoverageDetail, coverage_with_synonyms

logger = logging.getLogger(__name__)


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class RetrievalEvaluation:
    context_precision: float
    context_recall: float
    context_relevancy: float
    retrieval_score: float
    precision_reason: str = ""
    recall_gaps: str = ""
    noise_examples: str = ""


@dataclass
class GenerationEvaluation:
    faithfulness: float
    answer_relevancy: float
    answer_completeness: float
    generation_score: float
    hallucinated_claims: list[str] = field(default_factory=list)
    missing_aspects: list[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class HallucinationDetail:
    """1 主張ごとの裏付け判定."""

    claim: str
    status: str       # "supported" | "partially_supported" | "not_supported"
    evidence: str = ""


@dataclass
class SupplementaryMetrics:
    hallucination_rate: float
    keyword_coverage: float
    latency_ms: float
    keyword_matched: list[str] = field(default_factory=list)
    keyword_missed: list[str] = field(default_factory=list)
    keyword_only_in_context: list[str] = field(default_factory=list)
    hallucination_claims: list[HallucinationDetail] = field(default_factory=list)


@dataclass
class EvaluationResultV2:
    query_id: str
    method_id: str
    method_name: str
    retrieval_eval: RetrievalEvaluation
    generation_eval: GenerationEvaluation
    supplementary: SupplementaryMetrics
    composite_score: float
    eval_time_ms: float
    eval_input_tokens: int
    eval_output_tokens: int
    eval_metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# プロンプト
# =============================================================================


RETRIEVAL_EVAL_SYSTEM = """\
あなたは RAG システムの「検索品質」を評価する専門家です.
ユーザの質問と、RAG システムが取得したコンテキスト (検索結果) を見て、
検索の品質を 3 軸で評価してください.

重要: 最終回答は提示されません. コンテキストのみを評価してください.
コンテキスト外の知識で「正しい」と判断してはいけません.

評価軸:
1. context_precision (0.0-1.0):
   取得されたコンテキストのうち、質問への回答に実際に役立つ情報を含むものの割合.
   - 1.0: 全てのコンテキストが質問に直接関連する有用な情報を含む
   - 0.5: 半分程度が有用、残りはノイズ
   - 0.0: 全てが無関係

2. context_recall (0.0-1.0):
   質問に正しく回答するために必要な情報が、コンテキスト内にどれだけ含まれているか.
   期待キーワードと期待される回答方向を参考に判定.
   - 1.0: 完全に回答可能な情報が揃っている
   - 0.5: 部分的に情報がある (重要な観点が欠落)
   - 0.0: 回答に必要な情報が全く含まれていない

3. context_relevancy (0.0-1.0):
   コンテキスト全体として、質問のトピック・意図にどれだけ合致しているか.
   - 1.0: 質問の意図を完全に捉えた検索結果
   - 0.5: トピックは合っているが焦点がズレている
   - 0.0: 質問と無関係な検索結果

小数第 2 位まで (例: 0.75).

JSON で返してください:
{
  "context_precision": <float>,
  "context_recall": <float>,
  "context_relevancy": <float>,
  "precision_reason": "<関連/非関連コンテキストの内訳, 100 字以内>",
  "recall_gaps": "<不足している情報があれば記載, 100 字以内>",
  "noise_examples": "<ノイズとなっている非関連コンテキストの例, 100 字以内>"
}
"""


GENERATION_EVAL_SYSTEM = """\
あなたは RAG システムの「回答生成品質」を評価する専門家です.
ユーザの質問、提供されたコンテキスト、そしてシステムの回答を見て、
回答の品質を 3 軸で評価してください.

重要: コンテキストに含まれる情報のみを根拠として評価してください.
コンテキスト外の知識で「正しい」と判断してはいけません.

評価軸:
1. faithfulness (0.0-1.0):
   回答に含まれる各主張・記述が、提供されたコンテキストの情報に裏付けられているか.
   コンテキストに根拠がない情報を回答に含めていたら減点 (ハルシネーション).
   - 1.0: 全ての主張がコンテキストから直接導ける
   - 0.7: 大部分は裏付けあるが一部推測や外部知識を含む
   - 0.3: 回答の多くがコンテキストに裏付けがない
   - 0.0: 回答がコンテキストと完全に無関係

2. answer_relevancy (0.0-1.0):
   回答が質問に直接的に答えているか. 冗長な前置きや的外れな情報は減点.
   - 1.0: 質問の核心に直接答えている
   - 0.5: 部分的に答えているが焦点がズレている部分もある
   - 0.0: 質問に全く答えていない

3. answer_completeness (0.0-1.0):
   期待される回答方向の主要観点を網羅しているか.
   - 1.0: 期待される全ての観点をカバー
   - 0.5: 半分程度の観点をカバー
   - 0.0: 主要観点が全て欠落

小数第 2 位まで.

JSON で返してください:
{
  "faithfulness": <float>,
  "answer_relevancy": <float>,
  "answer_completeness": <float>,
  "hallucinated_claims": ["<コンテキストに裏付けのない主張, 最大 5 件>"],
  "missing_aspects": ["<回答に欠落している観点, 最大 5 件>"],
  "comment": "<50 字以内の総評>"
}
"""


HALLUCINATION_SYSTEM = """\
あなたはハルシネーション検出器です.
回答に含まれる「事実の主張」を最大 10 個列挙し、各主張がコンテキストに
裏付けられているかを判定してください.

各主張の status:
- "supported"           : コンテキストに明確な根拠がある
- "partially_supported" : 関連情報はあるが直接的な裏付けではない
- "not_supported"       : コンテキストに根拠が見当たらない

JSON で返してください:
{
  "claims": [
    {"claim": "<主張文, 80 字以内>",
     "status": "supported|partially_supported|not_supported",
     "evidence": "<裏付けがある場合のコンテキスト該当部分, 80 字以内>"}
  ],
  "hallucination_rate": <0.0-1.0, not_supported / 全主張>
}
"""


# =============================================================================
# 補助関数
# =============================================================================


def _safe_float(v: Any, default: float = 0.0) -> float:
    """0.0 - 1.0 にクランプ. 数値化に失敗したら default."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return round(f, 3)


def _format_contexts(contexts: list[str], per_ctx_max_chars: int = 1500) -> str:
    """評価プロンプト用にコンテキストを整形.

    各コンテキストは長すぎる場合のみ末尾を切る. 評価器に渡す全体長を抑える.
    """
    if not contexts:
        return "(コンテキスト無し)"
    parts: list[str] = []
    for i, c in enumerate(contexts, 1):
        body = (c or "").strip()
        if len(body) > per_ctx_max_chars:
            body = body[:per_ctx_max_chars] + " ...[省略]"
        parts.append(f"--- Context #{i} ---\n{body}")
    return "\n\n".join(parts)


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


# =============================================================================
# Retrieval 評価
# =============================================================================


def evaluate_retrieval(
    llm: LLMClient,
    query_text: str,
    expected_direction: str,
    keywords: list[str],
    contexts: list[str],
) -> tuple[RetrievalEvaluation, int, int, str]:
    """コンテキストのみを見て検索品質を採点.

    Returns
    -------
    (RetrievalEvaluation, input_tokens, output_tokens, raw_response)
    """
    user_prompt = (
        f"【質問】\n{query_text}\n\n"
        f"【期待される回答方向】\n{expected_direction}\n\n"
        f"【正解に含まれるべきキーワード】\n{', '.join(keywords)}\n\n"
        f"【RAG システムが取得したコンテキスト (検索結果)】\n{_format_contexts(contexts)}\n\n"
        "上記のコンテキストの検索品質を 3 軸で評価してください."
    )
    try:
        chat = llm.chat(
            RETRIEVAL_EVAL_SYSTEM,
            user_prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(chat.text)
        precision = _safe_float(parsed.get("context_precision"))
        recall = _safe_float(parsed.get("context_recall"))
        relevancy = _safe_float(parsed.get("context_relevancy"))
        ev = RetrievalEvaluation(
            context_precision=precision,
            context_recall=recall,
            context_relevancy=relevancy,
            retrieval_score=_avg([precision, recall, relevancy]),
            precision_reason=str(parsed.get("precision_reason", ""))[:200],
            recall_gaps=str(parsed.get("recall_gaps", ""))[:200],
            noise_examples=str(parsed.get("noise_examples", ""))[:200],
        )
        return ev, chat.input_tokens, chat.output_tokens, chat.text
    except Exception as e:  # noqa: BLE001
        logger.warning("[eval_v2] retrieval 評価失敗: %s", e)
        return (
            RetrievalEvaluation(
                context_precision=0.0,
                context_recall=0.0,
                context_relevancy=0.0,
                retrieval_score=0.0,
                precision_reason=f"[ERROR] {e}",
            ),
            0,
            0,
            "",
        )


# =============================================================================
# Generation 評価
# =============================================================================


def evaluate_generation(
    llm: LLMClient,
    query_text: str,
    expected_direction: str,
    keywords: list[str],
    contexts: list[str],
    answer: str,
) -> tuple[GenerationEvaluation, int, int, str]:
    user_prompt = (
        f"【質問】\n{query_text}\n\n"
        f"【期待される回答方向】\n{expected_direction}\n\n"
        f"【正解キーワード】\n{', '.join(keywords)}\n\n"
        f"【提供されたコンテキスト】\n{_format_contexts(contexts)}\n\n"
        f"【システムの回答】\n{answer or '(回答無し)'}\n\n"
        "上記の回答の生成品質を 3 軸で評価してください."
    )
    try:
        chat = llm.chat(
            GENERATION_EVAL_SYSTEM,
            user_prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(chat.text)
        faith = _safe_float(parsed.get("faithfulness"))
        relevancy = _safe_float(parsed.get("answer_relevancy"))
        complete = _safe_float(parsed.get("answer_completeness"))
        hallu_claims = [str(s)[:200] for s in parsed.get("hallucinated_claims", []) or []][:5]
        missing = [str(s)[:200] for s in parsed.get("missing_aspects", []) or []][:5]
        comment = str(parsed.get("comment", ""))[:200]
        ev = GenerationEvaluation(
            faithfulness=faith,
            answer_relevancy=relevancy,
            answer_completeness=complete,
            generation_score=_avg([faith, relevancy, complete]),
            hallucinated_claims=hallu_claims,
            missing_aspects=missing,
            comment=comment,
        )
        return ev, chat.input_tokens, chat.output_tokens, chat.text
    except Exception as e:  # noqa: BLE001
        logger.warning("[eval_v2] generation 評価失敗: %s", e)
        return (
            GenerationEvaluation(
                faithfulness=0.0,
                answer_relevancy=0.0,
                answer_completeness=0.0,
                generation_score=0.0,
                comment=f"[ERROR] {e}",
            ),
            0,
            0,
            "",
        )


# =============================================================================
# Hallucination 検出
# =============================================================================


def detect_hallucinations(
    llm: LLMClient,
    contexts: list[str],
    answer: str,
) -> tuple[float, list[HallucinationDetail], int, int, str]:
    if not (answer or "").strip():
        return 1.0, [], 0, 0, ""
    user_prompt = (
        f"【提供されたコンテキスト】\n{_format_contexts(contexts)}\n\n"
        f"【システムの回答】\n{answer}\n\n"
        "回答に含まれる事実の主張を列挙し、各主張の裏付け状況を判定してください."
    )
    try:
        chat = llm.chat(
            HALLUCINATION_SYSTEM,
            user_prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(chat.text)
        claims_raw = parsed.get("claims", []) or []
        claims: list[HallucinationDetail] = []
        for c in claims_raw[:10]:
            status = str(c.get("status", "")).lower()
            if status not in {"supported", "partially_supported", "not_supported"}:
                status = "not_supported"
            claims.append(
                HallucinationDetail(
                    claim=str(c.get("claim", ""))[:200],
                    status=status,
                    evidence=str(c.get("evidence", ""))[:200],
                )
            )
        if claims:
            ns = sum(1 for c in claims if c.status == "not_supported")
            rate = round(ns / len(claims), 3)
        else:
            rate = _safe_float(parsed.get("hallucination_rate"))
        # LLM が直接返した hallucination_rate がより低い場合はそちらを採用しない
        # (主張数からの実測を優先)
        return rate, claims, chat.input_tokens, chat.output_tokens, chat.text
    except Exception as e:  # noqa: BLE001
        logger.warning("[eval_v2] hallucination 検出失敗: %s", e)
        return 0.0, [], 0, 0, ""


# =============================================================================
# 1 ジョブ評価
# =============================================================================


DEFAULT_WEIGHTS: dict[str, float] = {
    "retrieval": 0.4,
    "generation": 0.5,
    "keyword": 0.1,
}


def evaluate_job(
    llm: LLMClient,
    query_id: str,
    query_text: str,
    expected_direction: str,
    keywords: list[str],
    method_id: str,
    method_name: str,
    contexts: list[str],
    answer: str,
    latency_ms: float,
    skip_hallucination: bool = False,
    weights: dict[str, float] | None = None,
) -> EvaluationResultV2:
    """1 (method, query) の RAGAS 評価を実行する."""
    weights = weights or DEFAULT_WEIGHTS
    t0 = time.perf_counter()

    retrieval_ev, in1, out1, _ = evaluate_retrieval(
        llm, query_text, expected_direction, keywords, contexts,
    )
    generation_ev, in2, out2, _ = evaluate_generation(
        llm, query_text, expected_direction, keywords, contexts, answer,
    )

    if skip_hallucination:
        hallu_rate = 0.0
        hallu_claims: list[HallucinationDetail] = []
        in3 = 0
        out3 = 0
    else:
        hallu_rate, hallu_claims, in3, out3, _ = detect_hallucinations(
            llm, contexts, answer,
        )

    cov: CoverageDetail = coverage_with_synonyms(keywords, answer, contexts)

    composite = (
        weights["retrieval"] * retrieval_ev.retrieval_score
        + weights["generation"] * generation_ev.generation_score
        + weights["keyword"] * cov.coverage
    ) * 100.0

    supplementary = SupplementaryMetrics(
        hallucination_rate=hallu_rate,
        keyword_coverage=cov.coverage,
        latency_ms=round(float(latency_ms), 1) if latency_ms is not None else -1.0,
        keyword_matched=cov.matched,
        keyword_missed=cov.missed,
        keyword_only_in_context=cov.only_in_context,
        hallucination_claims=hallu_claims,
    )

    elapsed = (time.perf_counter() - t0) * 1000.0
    return EvaluationResultV2(
        query_id=query_id,
        method_id=method_id,
        method_name=method_name,
        retrieval_eval=retrieval_ev,
        generation_eval=generation_ev,
        supplementary=supplementary,
        composite_score=round(composite, 2),
        eval_time_ms=round(elapsed, 1),
        eval_input_tokens=in1 + in2 + in3,
        eval_output_tokens=out1 + out2 + out3,
        eval_metadata={"weights": weights, "skip_hallucination": skip_hallucination},
    )


# =============================================================================
# 診断 (retrieval vs generation の差分による失敗原因分類)
# =============================================================================


def diagnose(retrieval_score: float, generation_score: float) -> str:
    """retrieval/generation スコアから失敗原因を分類する.

    Categories
    ----------
    retrieval_failure  : 検索が悪く生成は問題なし
    generation_failure : 検索は良いが生成で失敗
    both_weak          : 両方とも弱い
    both_good          : 両方とも良好
    mixed              : それ以外 (片方平均的)
    """
    r, g = retrieval_score, generation_score
    if r < 0.4 and g > 0.6:
        return "retrieval_failure"
    if r > 0.6 and g < 0.4:
        return "generation_failure"
    if r < 0.5 and g < 0.5:
        return "both_weak"
    if r > 0.7 and g > 0.7:
        return "both_good"
    return "mixed"
