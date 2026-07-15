"""LLM ベースの回答評価モジュール.

評価軸 (各 0-10 点, 10 が最高):
  1. relevance      - 質問に直接答えているか
  2. accuracy       - コンテキストに基づき事実誤認がないか
  3. completeness   - 期待される観点を網羅しているか
  4. specificity    - 具体例・数値・固有名詞を含むか
  5. structure      - 論理構造が明確で読みやすいか

追加スコア:
  - keyword_coverage   : ground_truth_keywords の含有率 (0-1)
  - speed_score        : total_time_ms から正規化 (0-1, 速いほど高い)
  - composite_score    : 上記を重み付き統合 (0-100)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


EVAL_SYSTEM_PROMPT = """
あなたはセンサ商談 RAG システムの評価器です. ユーザの質問と提供された回答を見て、
以下の 5 軸でそれぞれ 0-10 の整数で評価してください. 10 が最高、0 が最低.

  - relevance     (関連性): 質問に直接答えているか. 質問と無関係な内容は減点.
  - accuracy      (正確性): 不正確な記述や矛盾、ハルシネーションが無いか.
  - completeness  (網羅性): 期待される回答方向の主要な観点を網羅しているか.
  - specificity   (具体性): 具体例、数値、固有名詞 (機器名・工程名等) を含むか.
  - structure     (構造性): 結論・根拠・補足が論理的に整理され読みやすいか.

さらに、回答全体に対する短い講評 (50 字以内) と、目立った弱点キーワード (例: "ハルシネーション", "曖昧",
"情報不足", "重複多い", "回答無し" 等) を最大 3 個タグ付けしてください.

JSON で返してください:
{
  "scores": {"relevance": <int>, "accuracy": <int>, "completeness": <int>,
             "specificity": <int>, "structure": <int>},
  "comment": "<50字以内>",
  "weakness_tags": ["<tag1>", "<tag2>", ...]
}
""".strip()


@dataclass
class EvaluationResult:
    query_id: str
    method_id: str
    method_name: str
    scores: dict[str, int]                # relevance, accuracy, completeness, specificity, structure
    comment: str
    weakness_tags: list[str]
    keyword_coverage: float               # 0-1
    speed_score: float                    # 0-1
    quality_score: float                  # 5軸平均 → 0-1 にスケール
    composite_score: float                # 総合 0-100
    eval_time_ms: float
    eval_input_tokens: int
    eval_output_tokens: int
    raw_llm_response: str = ""


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return max(0, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def evaluate_answer(
    llm: LLMClient,
    query_id: str,
    query_text: str,
    expected_direction: str,
    ground_truth_keywords: list[str],
    method_id: str,
    method_name: str,
    answer: str,
    total_time_ms: float,
    speed_norm_total_ms: float = 50000.0,
    weights: dict[str, float] | None = None,
) -> EvaluationResult:
    """1 (手法 × クエリ) の回答を LLM 採点 + ルールベース集計.

    Parameters
    ----------
    speed_norm_total_ms : float
        速度スコアの正規化基準. これ以上かかったジョブは speed_score=0、0ms で 1.0.
        50,000ms (50秒) を 0 点ラインに設定.
    weights : dict
        composite_score の重み. default: {"quality": 0.7, "keyword": 0.15, "speed": 0.15}
    """
    weights = weights or {"quality": 0.7, "keyword": 0.15, "speed": 0.15}

    t0 = time.perf_counter()

    # ---------- LLM 採点 ----------
    user_prompt = (
        f"【質問】\n{query_text}\n\n"
        f"【期待される回答方向】\n{expected_direction}\n\n"
        f"【正解に含まれていてほしいキーワード例】\n{', '.join(ground_truth_keywords)}\n\n"
        f"【評価対象の回答 (手法={method_id} {method_name})】\n{answer or '(回答無し)'}"
    )
    try:
        chat = llm.chat(
            EVAL_SYSTEM_PROMPT, user_prompt,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(chat.text)
        raw_scores = parsed.get("scores", {})
        scores = {
            "relevance":    _safe_int(raw_scores.get("relevance")),
            "accuracy":     _safe_int(raw_scores.get("accuracy")),
            "completeness": _safe_int(raw_scores.get("completeness")),
            "specificity":  _safe_int(raw_scores.get("specificity")),
            "structure":    _safe_int(raw_scores.get("structure")),
        }
        comment = str(parsed.get("comment", ""))[:200]
        weakness = [str(w) for w in parsed.get("weakness_tags", [])][:5]
        in_tok = chat.input_tokens
        out_tok = chat.output_tokens
        raw_resp = chat.text
    except Exception as e:  # noqa: BLE001
        logger.warning("[eval] %s/%s LLM 採点失敗: %s", method_id, query_id, e)
        scores = {"relevance": 0, "accuracy": 0, "completeness": 0,
                  "specificity": 0, "structure": 0}
        comment = f"[ERROR] {e}"
        weakness = ["評価エラー"]
        in_tok = 0
        out_tok = 0
        raw_resp = ""

    # ---------- キーワード一致率 ----------
    if ground_truth_keywords:
        hits = sum(1 for kw in ground_truth_keywords if kw and kw in (answer or ""))
        kw_cov = hits / len(ground_truth_keywords)
    else:
        kw_cov = 0.0

    # ---------- 速度スコア (0-1) ----------
    if total_time_ms < 0:
        speed_score = 0.0
    else:
        speed_score = max(0.0, 1.0 - (total_time_ms / speed_norm_total_ms))

    # ---------- 統合スコア ----------
    quality_avg = sum(scores.values()) / 5.0 / 10.0  # 0-1 にスケール
    composite = (
        weights["quality"] * quality_avg
        + weights["keyword"] * kw_cov
        + weights["speed"] * speed_score
    ) * 100.0

    elapsed = (time.perf_counter() - t0) * 1000.0
    return EvaluationResult(
        query_id=query_id,
        method_id=method_id,
        method_name=method_name,
        scores=scores,
        comment=comment,
        weakness_tags=weakness,
        keyword_coverage=round(kw_cov, 3),
        speed_score=round(speed_score, 3),
        quality_score=round(quality_avg, 3),
        composite_score=round(composite, 2),
        eval_time_ms=round(elapsed, 1),
        eval_input_tokens=in_tok,
        eval_output_tokens=out_tok,
        raw_llm_response=raw_resp,
    )
