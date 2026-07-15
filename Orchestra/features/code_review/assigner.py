"""パートリーダー割当: ``--focus`` 重みからリーダー設定を生成する。

設計書: ``doc/12_code_review.md`` §12.2.4
"""

from __future__ import annotations

from core.data_models import PartLeaderConfig, ScanResult
from features.code_review.constants import (
    CONCERN_TO_MODEL,
    CONCERN_TO_ROLE,
    FOCUS_PRESETS,
    LEVEL_HIGH_THRESHOLD,
    LEVEL_MEDIUM_THRESHOLD,
    MINOR_FILE_FRAGMENTS,
    WEIGHT_FULL_COVERAGE_THRESHOLD,
    WEIGHT_SKIP_THRESHOLD,
)


class PartLeaderAssigner:
    """``--focus`` 重みに基づいてパートリーダーを割り当てる。"""

    FOCUS_PRESETS = FOCUS_PRESETS
    CONCERN_TO_ROLE = CONCERN_TO_ROLE
    CONCERN_TO_MODEL = CONCERN_TO_MODEL

    def assign(
        self,
        scan_result: ScanResult,
        focus: str = "all",
    ) -> list[PartLeaderConfig]:
        weights = self.FOCUS_PRESETS.get(focus, self.FOCUS_PRESETS["all"])
        leaders: list[PartLeaderConfig] = []
        for concern, weight in weights.items():
            if weight < WEIGHT_SKIP_THRESHOLD:
                continue
            assigned = self._get_files_for_concern(scan_result, concern, weight)
            leaders.append(
                PartLeaderConfig(
                    concern=concern,
                    weight=weight,
                    assigned_files=assigned,
                    role_id=self.CONCERN_TO_ROLE.get(concern, ""),
                    model=self.CONCERN_TO_MODEL.get(concern, ""),
                    level=self._weight_to_level(weight),
                )
            )
        return leaders

    @staticmethod
    def _weight_to_level(weight: float) -> str:
        if weight >= LEVEL_HIGH_THRESHOLD:
            return "high"
        if weight >= LEVEL_MEDIUM_THRESHOLD:
            return "medium"
        return "low"

    @staticmethod
    def _get_files_for_concern(
        scan_result: ScanResult,
        concern: str,
        weight: float,
    ) -> list[str]:
        del concern  # 現状は concern 別の絞り込みは未実装
        all_files: list[str] = [
            f["path"]
            for f in scan_result.file_details
            if isinstance(f.get("path"), str)
        ]
        if weight >= WEIGHT_FULL_COVERAGE_THRESHOLD:
            return all_files
        return [f for f in all_files if not _is_minor_file(f)]


def _is_minor_file(rel_path: str) -> bool:
    """``MINOR_FILE_FRAGMENTS`` のいずれかを含む場合 True。"""
    normalized = rel_path.replace("\\", "/")
    for fragment in MINOR_FILE_FRAGMENTS:
        if fragment in normalized:
            return True
    return False


__all__ = ["PartLeaderAssigner"]
