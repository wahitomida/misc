"""AI Orchestra 共通データモデル (最小限の前倒し定義)。

設計書 ``doc/03_architecture.md`` §3.4, ``doc/08_memory_context.md`` のデータ
クラスのうち、Phase B / C から参照されるものだけを定義する。残り (``ODSC``,
``AgentConfig``, ``ConvergenceResult`` など) は使う Phase で追加する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# 発言パターン
RoundPattern = Literal["one_shot", "ping_pong", "free_talk"]

# 発言レベル
UtteranceLevel = Literal["minimal", "low", "medium", "high", "none"]


@dataclass
class TokenCount:
    """入出力 token 数の集計。

    Attributes:
        input: 入力 token 数の累積。
        output: 出力 token 数の累積。
        total: ``input + output``。集計時に更新する。
    """

    input: int = 0
    output: int = 0
    total: int = 0


@dataclass
class Utterance:
    """1 つの公開発言。

    Attributes:
        sequence: ラウンド内の通し番号 (1-indexed が一般的)。
        speaker: ``role_id``。
        speaker_display: 表示名 (絵文字付き)。
        type: 発言タイプ (``"discussion"`` / ``"instruction"`` など)。
        content: 発言本文。
        model: 使用モデル名。
        level: 発言時の level。
        tokens_used: ``{"input": int, "output": int}`` 形式の辞書。
        duration_sec: API 呼び出し所要秒数。
        reasoning_content: Claude 拡張思考の reasoning ログ (任意)。
    """

    sequence: int
    speaker: str
    speaker_display: str
    type: str
    content: str
    model: str
    level: str
    tokens_used: dict[str, int] = field(default_factory=dict)
    duration_sec: float = 0.0
    reasoning_content: str | None = None


@dataclass
class RoundConfig:
    """1 ラウンドの実行設定。

    Attributes:
        round: ラウンド番号 (1-indexed)。
        phase_name: ラウンドの名称 (例: "問題定式化")。
        speakers: 発言する ``role_id`` のリスト。
        pattern: 発言パターン (``one_shot`` / ``ping_pong`` / ``free_talk``)。
        level: 発言の深さ (``reasoning_effort`` の元になる)。
        time_budget_sec: このラウンドに割り当てる時間 (秒)。
        goal: 指揮者が設定した到達目標。
    """

    round: int
    phase_name: str
    speakers: list[str]
    pattern: str  # RoundPattern (Literal を緩める: YAML 由来も許容)
    level: str
    time_budget_sec: float
    goal: str


@dataclass
class DiscussionPlan:
    """Phase 1 で確定した議論計画。

    Attributes:
        estimated_rounds: 計画ラウンド数。
        round_config: ラウンドごとの設定。
        total_estimated_time_sec: 全ラウンド合計の推定所要時間 (秒)。
        total_estimated_requests: 全ラウンド合計の推定 API リクエスト数。
    """

    estimated_rounds: int
    round_config: list[RoundConfig] = field(default_factory=list)
    total_estimated_time_sec: float = 0.0
    total_estimated_requests: int = 0


@dataclass
class RoundLog:
    """1 ラウンドの実行結果 (Phase B/C で必要な最小フィールド)。

    Phase D で ``convergence_check`` などを追加する。

    Attributes:
        round: ラウンド番号。
        duration_sec: 実測所要時間 (秒)。
        phase_name: ラウンド名称 (要約生成時に使用)。
        goal: ラウンド目標 (要約生成時に使用)。
        public_utterances: ラウンド中の公開発言。
        convergence_check: 収束判定結果 (``ConvergenceResult`` または ``None``)。
    """

    round: int
    duration_sec: float
    phase_name: str = ""
    goal: str = ""
    public_utterances: list[Utterance] = field(default_factory=list)
    convergence_check: "ConvergenceResult | None" = None


# ----------------------------------------------------------------------
# Phase 2 (Conductor / Convergence) のデータ型
# ----------------------------------------------------------------------


@dataclass
class ConvergenceResult:
    """ラウンド終了時の収束判定結果。

    Attributes:
        score: 収束度 (0.0〜1.0)。
        reasoning: 合意度の根拠 (1〜2 文)。
        remaining_disagreements: 未解決の論点リスト。
        recommendation: ``"continue"`` / ``"conclude"`` / ``"pivot"`` のいずれか。
    """

    score: float
    reasoning: str = ""
    remaining_disagreements: list[str] = field(default_factory=list)
    recommendation: str = "continue"


@dataclass
class RepetitionResult:
    """堂々巡り検知の結果。

    Attributes:
        is_repeating: 繰り返しが起きているか。
        repeated_topic: 繰り返されている論点 (任意)。
        suggestion: 議論を前に進めるための提案 (任意)。
    """

    is_repeating: bool
    repeated_topic: str = ""
    suggestion: str = ""


@dataclass
class DiscussionLog:
    """Phase 2 の最終出力。

    Attributes:
        rounds: 全ラウンドのログ。
        total_requests: Conductor 配下の累積 API リクエスト数 (任意)。
        final_convergence_score: 最終ラウンドの収束スコア。
        early_termination: 早期終了理由 (``"converged"`` / ``"time_limit"`` /
            ``"force"`` など)。最後まで完走したなら ``None``。
        termination_detail: 早期終了の詳細メッセージ (任意)。
        score_history: 各ラウンドの収束スコア履歴。
    """

    rounds: list[RoundLog] = field(default_factory=list)
    total_requests: int = 0
    final_convergence_score: float = 0.0
    early_termination: str | None = None
    termination_detail: str = ""
    score_history: list[float] = field(default_factory=list)


# ----------------------------------------------------------------------
# Phase 3 (Evaluator) のデータ型
# ----------------------------------------------------------------------


@dataclass
class SelfEvaluation:
    """エージェント自身による振り返り評価。

    Attributes:
        scores: 評価項目名 → 1〜5 のスコア。
        avg_score: 平均スコア。``scores`` から再計算しても良い。
        reasoning: 3〜5 文の振り返り。
        key_contributions: 主な貢献のリスト。
        missed_opportunities: やれたはずでやらなかったことのリスト。
    """

    scores: dict[str, int] = field(default_factory=dict)
    avg_score: float = 0.0
    reasoning: str = ""
    key_contributions: list[str] = field(default_factory=list)
    missed_opportunities: list[str] = field(default_factory=list)


@dataclass
class PeerEvaluation:
    """他者から受けた 1 評価。

    Attributes:
        score: 1〜5 のスコア。
        comment: 1 行の具体的コメント。
    """

    score: int
    comment: str = ""


@dataclass
class AgentEvaluations:
    """1 エージェントが議論終了時にまとめる評価結果。

    Attributes:
        self_eval: 自分自身による振り返り。
        peer_evals: 自分が他者に与えた評価 (``role_id`` → ``PeerEvaluation``)。
    """

    self_eval: SelfEvaluation
    peer_evals: dict[str, PeerEvaluation] = field(default_factory=dict)


@dataclass
class ODSCAchievement:
    """指揮者による ODSC 達成度判定。

    Attributes:
        achieved: 総合的に達成されたか。
        detail: 達成度の説明文。
        objective_met: Objective 単体の達成。
        deliverable_met: Deliverable 単体の達成。
        criteria_met: Success Criteria 単体の達成。
        convergence_final: 最終収束スコア。
    """

    achieved: bool = False
    detail: str = ""
    objective_met: bool = False
    deliverable_met: bool = False
    criteria_met: bool = False
    convergence_final: float = 0.0


@dataclass
class AgentFeedback:
    """指揮者から各エージェントへの個別フィードバック。

    Attributes:
        strengths_noted: 良かった点のリスト (2〜3 個)。
        improvements_noted: 改善すべき点のリスト (1〜2 個)。
        orchestrator_feedback: 次回への期待 (1 文)。
    """

    strengths_noted: list[str] = field(default_factory=list)
    improvements_noted: list[str] = field(default_factory=list)
    orchestrator_feedback: str = ""


@dataclass
class OrchestratorEvaluation:
    """指揮者による議論全体の総合評価。

    Attributes:
        overall_discussion_quality: 1.0〜5.0 の議論品質スコア。
        mvp_role_id: MVP の ``role_id``。
        mvp_reason: MVP 選出理由。
        odsc_achievement: ODSC 達成度。
        per_agent_feedback: ``role_id`` → ``AgentFeedback``。
    """

    overall_discussion_quality: float = 0.0
    mvp_role_id: str = ""
    mvp_reason: str = ""
    odsc_achievement: ODSCAchievement = field(default_factory=ODSCAchievement)
    per_agent_feedback: dict[str, AgentFeedback] = field(default_factory=dict)


@dataclass
class FollowUpContext:
    """フォローアップセッションの引き継ぎコンテキスト (Phase F-1 で詳細化)。

    本ステップ (Phase E-4) では ``IdeaDiscussion`` がスタブとして
    生成する最小限の構造のみを定義する。``FollowUpManager`` (F-1) が
    過去 ``session_meta.json`` / ``report.md`` から完全版を組み立てる。

    Attributes:
        parent_session_id: 前回セッション ID。
        previous_conclusion: 前回の結論。
        previous_hypotheses: 前回の仮説テーブル
            (``[{"id", "hypothesis", "status", "verification"}]``)。
        unresolved_issues: 前回の未解決問題。
        discussion_summary: 前回議論の圧縮要約。
        previous_agents: 前回の参加エージェント情報。
        previous_feedback: 前回の指揮者総合フィードバック。
        new_input: 今回追加された情報。
        attached_files: 添付ファイル
            (``[{"name", "content"}]``)。
        focus_hypotheses: 重点的に検証したい仮説 ID のリスト。
        chain: チェーン全体 (``[parent_session_id, ..., current_session_id]``)。
        chain_depth: チェーン深さ。
    """

    parent_session_id: str | None = None
    previous_conclusion: str = ""
    previous_hypotheses: list[dict[str, str]] = field(default_factory=list)
    unresolved_issues: list[str] = field(default_factory=list)
    discussion_summary: str = ""
    previous_agents: list[dict[str, Any]] = field(default_factory=list)
    previous_feedback: dict[str, Any] = field(default_factory=dict)
    new_input: str = ""
    attached_files: list[dict[str, str]] = field(default_factory=list)
    focus_hypotheses: list[str] = field(default_factory=list)
    chain: list[str] = field(default_factory=list)
    chain_depth: int = 0


@dataclass
class SynthesisResult:
    """Phase 3 の最終成果物 (Synthesizer の戻り値)。

    レポート系の文字列フィールドは D-4 後半で生成する。本ステップでは
    ``orchestrator_evaluation`` / ``agent_evaluations`` / ``session_meta``
    のみが埋まる。

    Attributes:
        report_md: 議論レポート (``report.md`` 用)。
        full_conversation_md: 会話ログ (``full_conversation.md`` 用)。
        evaluation_md: 評価レポート (``evaluation.md`` 用)。
        summary_txt: コンパクトサマリ (``summary.txt`` 用)。
        vibe_coding_prompt_md: コードレビュー出力 (機能② のみ)。
        agent_evaluations: ``role_id`` → ``AgentEvaluations`` (生データ)。
        orchestrator_evaluation: 指揮者による総合評価。
        feedback_updates: ロール YAML 更新用データ (E-1 で埋める)。
        session_meta: ``session_meta.json`` 用辞書。
    """

    report_md: str = ""
    full_conversation_md: str = ""
    evaluation_md: str = ""
    summary_txt: str = ""
    vibe_coding_prompt_md: str | None = None
    agent_evaluations: dict[str, AgentEvaluations] = field(default_factory=dict)
    orchestrator_evaluation: OrchestratorEvaluation = field(
        default_factory=OrchestratorEvaluation
    )
    feedback_updates: dict[str, Any] = field(default_factory=dict)
    session_meta: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Phase 1 (Orchestrator) のデータ型
# ----------------------------------------------------------------------


@dataclass
class ODSC:
    """議論のゴール定義 (Objective / Deliverable / Success Criteria + 閾値)。

    Attributes:
        objective: 議論で達成すべきこと (1 文)。
        deliverable: 議論の成果物の形式と内容。
        success_criteria: 議論が成功したと判定する基準。
        convergence_threshold: 収束判定の閾値 (0.0〜1.0)。
    """

    objective: str
    deliverable: str
    success_criteria: str
    convergence_threshold: float


@dataclass
class AgentConfig:
    """Phase 1 で指揮者が決定するエージェント設定。

    Attributes:
        role_id: ロール識別子。
        model: 使用モデル名。
        level: 発言レベル (``minimal``/``low``/``medium``/``high``/``none``)。
        reason: このロールを選んだ理由 (記録用)。
        expected_contribution: 期待される貢献内容 (記録用)。
    """

    role_id: str
    model: str
    level: str
    reason: str = ""
    expected_contribution: str = ""


@dataclass
class PrivateInstruction:
    """ラウンド開始時に各エージェントへ渡される個別指示。

    Attributes:
        role_id: 対象エージェントの ``role_id``。
        expected_contribution: このラウンドで期待する貢献。
        focus_points: 特に注意してほしい観点のリスト。
        constraints: やってはいけないことのリスト。
        context_from_plan: 議論計画上の位置づけ。
        feedback_reminder: 過去フィードバックからの改善依頼。
        speaking_rules: 発言形式のルール (共通 + ロール固有)。
    """

    role_id: str
    expected_contribution: str
    focus_points: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    context_from_plan: str = ""
    feedback_reminder: str = ""
    speaking_rules: str = ""


@dataclass
class OrchestraPlan:
    """Phase 1 の最終成果物。

    Attributes:
        odsc: 議論のゴール定義。
        selected_agents: 参加エージェントのリスト。
        discussion_plan: ラウンド構成と推定値。
        private_instructions: ``role_id`` → ``PrivateInstruction`` の辞書。
    """

    odsc: ODSC
    selected_agents: list[AgentConfig] = field(default_factory=list)
    discussion_plan: "DiscussionPlan | None" = None
    private_instructions: dict[str, PrivateInstruction] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 機能② (Code Review) のデータ型
# ----------------------------------------------------------------------


@dataclass
class ScanResult:
    """``FolderScanner.scan`` の結果。

    Attributes:
        target_path: スキャン対象のルートパス。
        file_tree: スキャンした全ファイルのメタ情報リスト。
            各要素は ``{"path", "size_bytes", "extension", "lines",
            "header"?, "skipped"?, "skip_reason"?}``。
        file_details: ヘッダまで読み込めたファイル (``skipped`` でないもの)。
        total_files: スキャンしたファイル総数。
        total_lines: ファイル行数の合計。
        skipped_files: サイズ超過などでスキップされたファイル情報。
    """

    target_path: Path
    file_tree: list[dict[str, Any]] = field(default_factory=list)
    file_details: list[dict[str, Any]] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    skipped_files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PartLeaderConfig:
    """コードレビューにおけるパートリーダーの設定。

    Attributes:
        concern: 担当観点 (``algorithm`` / ``reproducibility`` /
            ``performance`` / ``structure`` / ``readability`` / ``results``)。
        weight: ``--focus`` で決まる重み (0.0〜2.0)。
        assigned_files: 担当するファイル相対パスのリスト。
        role_id: ``CONCERN_TO_ROLE`` で解決されるロール ID。
        model: ``CONCERN_TO_MODEL`` で解決されるモデル名。
        level: 重みから派生する level (``low`` / ``medium`` / ``high``)。
    """

    concern: str
    weight: float
    assigned_files: list[str] = field(default_factory=list)
    role_id: str = ""
    model: str = ""
    level: str = "medium"


__all__ = [
    "RoundConfig",
    "DiscussionPlan",
    "RoundLog",
    "RoundPattern",
    "UtteranceLevel",
    "TokenCount",
    "Utterance",
    "ODSC",
    "AgentConfig",
    "PrivateInstruction",
    "OrchestraPlan",
    "ConvergenceResult",
    "RepetitionResult",
    "DiscussionLog",
    "SelfEvaluation",
    "PeerEvaluation",
    "AgentEvaluations",
    "ODSCAchievement",
    "AgentFeedback",
    "OrchestratorEvaluation",
    "FollowUpContext",
    "SynthesisResult",
    "ScanResult",
    "PartLeaderConfig",
]
