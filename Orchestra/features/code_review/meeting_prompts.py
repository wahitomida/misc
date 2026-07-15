"""Code Review 全体会議 (Phase 4) が使用するプロンプト定数と会議設定。

責務:
    - LLM 呼び出し用プロンプトテンプレート (SPEAKING_RULES / GOAL / OBJECTIVE) を集約
    - 3 ラウンドの構成値 (phase_name / goal / pattern / time_budget) を集約
    - 会議全体の hyperparameter (level / time_limit / preview 件数) を集約

背景:
    ``features/code_review/meeting.py`` は会議の実行・エージェント構築・
    プラン組立を担うロジック中心のモジュール。プロンプト仕様や会議設定は
    独立して調整されるため、混在させると仕様変更のたびにロジック側を
    diff する必要が生じて可読性が落ちる。Idea 側の
    ``core/conductor_prompts.py`` と同じパターンで分離する。

外部からの参照:
    ``meeting.py`` が ``from .meeting_prompts import (...)`` で取り込む。
    ``phases.py`` / テストは ``from features.code_review.meeting import ...``
    で継続参照できる (``meeting.py`` 側で再エクスポート)。
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# 会議全体の hyperparameter
# ----------------------------------------------------------------------

MEETING_PHASE_NAME = "全体会議"
MEETING_LEVEL = "medium"
MEETING_LEVEL_LOW = "low"
MEETING_TIME_BUDGET_SEC = 90.0
MEETING_TIME_LIMIT_SEC = 240.0
DEFAULT_CONVERGENCE_THRESHOLD = 0.7
MEETING_FINDINGS_PREVIEW = 3


# ----------------------------------------------------------------------
# 3 ラウンド構成
# ----------------------------------------------------------------------

ROUND1_PHASE_NAME = "課題報告と問題提起"
ROUND1_GOAL = "各リーダーが最重要課題を1つ報告し、具体的なファイル名・行番号・影響範囲まで含めて論点を提示する"
ROUND1_PATTERN = "one_shot"
ROUND1_TIME_BUDGET_SEC = 60.0

ROUND2_PHASE_NAME = "深掘りと反論"
ROUND2_GOAL = (
    "他者の所見への反論・補足で論点を深掘りする。"
    "反論は「前提崩し / エッジケース / スケール問題」のいずれかを明示的に選ぶ。"
    "反論後は必ず修復案を 1 つ添える"
)
ROUND2_PATTERN = "free_talk"
ROUND2_TIME_BUDGET_SEC = 120.0
ROUND2_MAX_UTTERANCES = 8

ROUND3_PHASE_NAME = "合意形成"
ROUND3_GOAL = (
    "Phase A/B/C の修正順序と副作用を確定する。"
    "各 Phase について「何を先に直すか」「副作用の想定」を 1 文ずつ明示する"
)
ROUND3_PATTERN = "one_shot"
ROUND3_TIME_BUDGET_SEC = 60.0


# ----------------------------------------------------------------------
# プロンプトテンプレート
# ----------------------------------------------------------------------

# 注: Review 会議固有の発言ルール (MEETING_SPEAKING_RULES) は削除しました。
# Idea Discussion と議論の質感を統一するため、Review でも Idea と同じ
# 共通の仕組み (role_base_template.txt の【会話の態度】/ DIVERSITY_RULE /
# 各ロール YAML の【発言の型】) だけを使用します。


MEETING_GOAL_TEMPLATE = """\
各パートリーダーの調査結果を共有し、3ラウンドで以下を決める:
1. Round 1: 各リーダーが最重要課題を1つ報告
2. Round 2: 互いの所見へ反論・深掘り
3. Round 3: Phase A/B/C 修正順序と副作用を確定
"""


MEETING_OBJECTIVE_TEMPLATE = """\
コードレビュー対象: {target_path}
focus: {focus}
合計 findings 件数: {total_findings}
全体会議で課題の優先度付け・修正順序・副作用を合意する。
"""


__all__ = [
    # hyperparameter
    "MEETING_PHASE_NAME",
    "MEETING_LEVEL",
    "MEETING_LEVEL_LOW",
    "MEETING_TIME_BUDGET_SEC",
    "MEETING_TIME_LIMIT_SEC",
    "DEFAULT_CONVERGENCE_THRESHOLD",
    "MEETING_FINDINGS_PREVIEW",
    # Round 1
    "ROUND1_PHASE_NAME",
    "ROUND1_GOAL",
    "ROUND1_PATTERN",
    "ROUND1_TIME_BUDGET_SEC",
    # Round 2
    "ROUND2_PHASE_NAME",
    "ROUND2_GOAL",
    "ROUND2_PATTERN",
    "ROUND2_TIME_BUDGET_SEC",
    "ROUND2_MAX_UTTERANCES",
    # Round 3
    "ROUND3_PHASE_NAME",
    "ROUND3_GOAL",
    "ROUND3_PATTERN",
    "ROUND3_TIME_BUDGET_SEC",
    # Prompts
    "MEETING_GOAL_TEMPLATE",
    "MEETING_OBJECTIVE_TEMPLATE",
]
