"""Phase 3: パートリーダー間の相互質問 (LLM 経由)。

設計書: ``doc/12_code_review.md`` §12.4
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.data_models import PartLeaderConfig
from features.code_review.prompts import (
    CROSS_QUESTION_ANSWER_PROMPT,
    CROSS_QUESTION_GENERATION_PROMPT,
    CROSS_QUESTION_PAIRS,
)

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient
    from core.config_loader import Settings

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------


DEFAULT_CROSS_QUESTION_MAX_ROUNDS = 5
DEFAULT_CROSS_QUESTION_MODEL = "gpt-4.1"
CROSS_QUESTION_TEMPERATURE = 0.3
CROSS_QUESTION_MAX_TOKENS = 300

_SKIP_TOKENS = (
    "特になし",
    "skip",
    "なし",
    "no question",
    "n/a",
    "該当なし",
)
_FINDINGS_PREVIEW_LIMIT = 5


# ----------------------------------------------------------------------
# CrossQuestioner
# ----------------------------------------------------------------------


class CrossQuestioner:
    """パートリーダー間の相互質問を実行し、findings を拡充する。"""

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        settings: "Settings | None" = None,
        model: str = DEFAULT_CROSS_QUESTION_MODEL,
    ) -> None:
        self.api_client = api_client
        self.model = model
        cr_config: dict[str, Any] = (
            getattr(settings, "code_review", {}) or {} if settings else {}
        )
        self.max_rounds: int = int(
            cr_config.get(
                "cross_question_max_rounds",
                DEFAULT_CROSS_QUESTION_MAX_ROUNDS,
            )
        )

    async def run(
        self,
        findings: dict[str, list[dict[str, Any]]],
        leaders: list[PartLeaderConfig],
    ) -> dict[str, list[dict[str, Any]]]:
        """相互質問を実行し、findings を info entry で拡充して返す。

        Args:
            findings: ``{concern: [finding, ...]}`` の Phase 2 結果。
            leaders: 現状未使用 (将来の weight 並び替えポイント)。

        Returns:
            入力を破壊せず複製したうえで、各 asker concern に info entry を
            追加した新しい辞書。
        """
        del leaders
        enriched = {k: list(v) for k, v in findings.items()}
        pairs = self._select_relevant_pairs(findings)

        for asker, answerer, hint in pairs:
            try:
                question = await self._generate_question(
                    asker,
                    answerer,
                    findings.get(asker, []),
                    findings.get(answerer, []),
                    hint,
                )
            except Exception as e:  # noqa: BLE001 - 1 ペア失敗で全体止めない
                logger.warning(
                    "Cross-question generation failed (%s -> %s): %s",
                    asker,
                    answerer,
                    e,
                )
                continue

            if not question or self._is_skip(question):
                continue

            try:
                answer = await self._get_answer(
                    answerer, question, findings.get(answerer, [])
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Cross-question answer failed (%s -> %s): %s",
                    asker,
                    answerer,
                    e,
                )
                continue

            if not answer:
                continue

            enriched.setdefault(asker, []).append(
                {
                    "severity": "info",
                    "title": f"[相互質問] {answerer} への質問結果",
                    "question": question,
                    "answer": answer,
                    "source": f"cross_question_{asker}->{answerer}",
                }
            )
        return enriched

    async def _generate_question(
        self,
        asker: str,
        answerer: str,
        asker_findings: list[dict[str, Any]],
        answerer_findings: list[dict[str, Any]],
        hint: str,
    ) -> str:
        prompt = CROSS_QUESTION_GENERATION_PROMPT.format(
            asker=asker,
            answerer=answerer,
            asker_findings=self._format_findings(asker_findings),
            answerer_findings=self._format_findings(answerer_findings),
            hint=hint,
        )
        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=CROSS_QUESTION_TEMPERATURE,
            max_tokens=CROSS_QUESTION_MAX_TOKENS,
        )
        return str(response.get("content") or "").strip()

    async def _get_answer(
        self,
        answerer: str,
        question: str,
        context: list[dict[str, Any]],
    ) -> str:
        prompt = CROSS_QUESTION_ANSWER_PROMPT.format(
            asker="(質問者)",
            answerer=answerer,
            question=question,
            answerer_findings=self._format_findings(context),
        )
        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=CROSS_QUESTION_TEMPERATURE,
            max_tokens=CROSS_QUESTION_MAX_TOKENS,
        )
        return str(response.get("content") or "").strip()

    def _select_relevant_pairs(
        self,
        findings: dict[str, list[dict[str, Any]]],
    ) -> list[tuple[str, str, str]]:
        """両 concern に findings があるペアのみ採用 (上限 ``max_rounds``)。"""
        relevant: list[tuple[str, str, str]] = []
        for asker, answerer, hint in CROSS_QUESTION_PAIRS:
            if not findings.get(asker) or not findings.get(answerer):
                continue
            relevant.append((asker, answerer, hint))
            if len(relevant) >= self.max_rounds:
                break
        return relevant

    @staticmethod
    def _format_findings(findings: list[dict[str, Any]]) -> str:
        if not findings:
            return "(所見なし)"
        lines: list[str] = []
        for f in findings[:_FINDINGS_PREVIEW_LIMIT]:
            severity = f.get("severity", "?")
            title = f.get("title", "(無題)")
            file_ref = f.get("file", "?")
            line_ref = f.get("line", "?")
            lines.append(f"- [{severity}] {file_ref} {line_ref}: {title}")
        remaining = len(findings) - _FINDINGS_PREVIEW_LIMIT
        if remaining > 0:
            lines.append(f"  ... 他 {remaining} 件")
        return "\n".join(lines)

    @staticmethod
    def _is_skip(question: str) -> bool:
        lower = question.lower()
        for token in _SKIP_TOKENS:
            if token in lower:
                return True
        return False


__all__ = [
    "CrossQuestioner",
    "DEFAULT_CROSS_QUESTION_MAX_ROUNDS",
    "DEFAULT_CROSS_QUESTION_MODEL",
]
