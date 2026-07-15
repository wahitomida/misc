# AI Orchestra — データモデル定義

> 全モジュール間で共有されるデータクラス・型定義の一覧

---

## 1. 設計方針

```
- dict より dataclass を優先する
- 全フィールドに型ヒントを付ける
- デフォルト値を持つフィールドは後方に配置する
- ミュータブルなデフォルトは field(default_factory=...) を使う
- JSON シリアライズが必要なものは to_dict() メソッドを持つ
- 不変データは frozen=True にする
```

---

## 2. Core データモデル

### 2.1 Agent 関連

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AgentConfig:
    """エージェントの構成情報。

    Attributes:
        role_id: ロールID (例: "theorist")。
        model: 使用モデル (例: "gpt-4.1")。
        level: 発言レベル ("concise" / "standard" / "detailed")。
        private_instruction: Orchestrator からの個別指示。
        feedback_context: 過去フィードバックに基づく改善指示。
    """
    role_id: str
    model: str
    level: str = "standard"
    private_instruction: str = ""
    feedback_context: str = ""


@dataclass
class Utterance:
    """1回の発言。

    Attributes:
        role_id: 発言者のロールID。
        role_name: 発言者の表示名。
        emoji: 発言者の絵文字。
        content: 発言内容テキスト。
        round_num: ラウンド番号。
        tokens: 使用トークン数。
        duration_sec: 生成所要時間（秒）。
        timestamp: 発言時刻。
    """
    role_id: str
    role_name: str
    emoji: str
    content: str
    round_num: int
    tokens: int = 0
    duration_sec: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """JSON シリアライズ用辞書を返す。"""
        return {
            "role_id": self.role_id,
            "role_name": self.role_name,
            "emoji": self.emoji,
            "content": self.content,
            "round_num": self.round_num,
            "tokens": self.tokens,
            "duration_sec": self.duration_sec,
            "timestamp": self.timestamp.isoformat(),
        }
```

### 2.2 Orchestrator 関連 (Phase 1)

```python
@dataclass
class ODSC:
    """議論の枠組み定義 (Objective / Deliverables / Scope / Criteria)。

    Attributes:
        objective: 議論の目的。
        deliverables: 期待される成果物。
        scope: 議論の範囲。
        criteria: 成功基準。
    """
    objective: str
    deliverables: str
    scope: str
    criteria: str

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "deliverables": self.deliverables,
            "scope": self.scope,
            "criteria": self.criteria,
        }


@dataclass
class RoundConfig:
    """1ラウンドの設定。

    Attributes:
        number: ラウンド番号 (1始まり)。
        phase: フェーズ名 ("diverge" / "deepen" / "converge")。
        pattern: 発言パターン ("one_shot" / "ping_pong" / "free_talk")。
        speakers: 発言者のロールIDリスト (順序が重要)。
        leader: 主導者のロールID (speakers[0])。
        topic: ラウンドのトピック/テーマ。
        estimated_sec: 推定所要時間（秒）。
        level: 発言レベル ("concise" / "standard" / "detailed")。
    """
    number: int
    phase: str
    pattern: str
    speakers: list[str]
    leader: str
    topic: str
    estimated_sec: float = 60.0
    level: str = "standard"

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "phase": self.phase,
            "pattern": self.pattern,
            "speakers": self.speakers,
            "leader": self.leader,
            "topic": self.topic,
            "estimated_sec": self.estimated_sec,
            "level": self.level,
        }


@dataclass
class PrivateInstruction:
    """エージェントへの個別指示。

    Attributes:
        role_id: 対象ロールID。
        instruction: 指示内容。
    """
    role_id: str
    instruction: str


@dataclass
class DiscussionPlan:
    """議論計画。

    Attributes:
        rounds: ラウンド設定リスト。
        estimated_total_sec: 推定合計時間（秒）。
        estimated_requests: 推定APIリクエスト数。
    """
    rounds: list[RoundConfig]
    estimated_total_sec: float = 0.0
    estimated_requests: int = 0

    def to_dict(self) -> dict:
        return {
            "rounds": [r.to_dict() for r in self.rounds],
            "estimated_total_sec": self.estimated_total_sec,
            "estimated_requests": self.estimated_requests,
        }


@dataclass
class OrchestraPlan:
    """Orchestrator の出力（完全な計画）。

    Attributes:
        theme: 議論テーマ。
        odsc: ODSC枠組み。
        agents: 参加エージェントのロールID一覧。
        agent_configs: エージェント別設定。
        discussion_plan: 議論計画。
        private_instructions: 個別指示リスト。
        scenario: 検出されたシナリオ名 (該当なしなら None)。
    """
    theme: str
    odsc: ODSC
    agents: list[str]
    agent_configs: dict[str, AgentConfig]
    discussion_plan: DiscussionPlan
    private_instructions: list[PrivateInstruction] = field(default_factory=list)
    scenario: str | None = None

    def to_dict(self) -> dict:
        return {
            "theme": self.theme,
            "odsc": self.odsc.to_dict(),
            "agents": self.agents,
            "agent_configs": {k: vars(v) for k, v in self.agent_configs.items()},
            "discussion_plan": self.discussion_plan.to_dict(),
            "private_instructions": [
                {"role_id": pi.role_id, "instruction": pi.instruction}
                for pi in self.private_instructions
            ],
            "scenario": self.scenario,
        }
```

### 2.3 Conductor 関連 (Phase 2)

```python
@dataclass
class RoundLog:
    """1ラウンドの実行ログ。

    Attributes:
        round_num: ラウンド番号。
        config: ラウンド設定。
        utterances: 全発言リスト。
        conclusion: ラウンド結論テキスト。
        concluder_role_id: 結論を出したロールID。
        convergence_score: 収束度スコア (0.0〜1.0)。
        duration_sec: 実績所要時間（秒）。
        total_tokens: ラウンド内の総トークン数。
    """
    round_num: int
    config: RoundConfig
    utterances: list[Utterance] = field(default_factory=list)
    conclusion: str = ""
    concluder_role_id: str = ""
    convergence_score: float = 0.0
    duration_sec: float = 0.0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "round_num": self.round_num,
            "config": self.config.to_dict(),
            "utterances": [u.to_dict() for u in self.utterances],
            "conclusion": self.conclusion,
            "concluder_role_id": self.concluder_role_id,
            "convergence_score": self.convergence_score,
            "duration_sec": self.duration_sec,
            "total_tokens": self.total_tokens,
        }


@dataclass
class DiscussionLog:
    """全議論ログ。

    Attributes:
        rounds: 全ラウンドログ。
        total_duration_sec: 合計所要時間。
        total_tokens: 合計トークン数。
        total_utterances: 合計発言数。
        final_convergence: 最終収束度。
    """
    rounds: list[RoundLog] = field(default_factory=list)
    total_duration_sec: float = 0.0
    total_tokens: int = 0
    total_utterances: int = 0
    final_convergence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "rounds": [r.to_dict() for r in self.rounds],
            "total_duration_sec": self.total_duration_sec,
            "total_tokens": self.total_tokens,
            "total_utterances": self.total_utterances,
            "final_convergence": self.final_convergence,
        }


@dataclass
class ConvergenceResult:
    """収束チェックの結果。

    Attributes:
        score: 収束度スコア (0.0〜1.0)。
        reason: 判定理由。
    """
    score: float
    reason: str
```

### 2.4 Synthesizer 関連 (Phase 3)

```python
@dataclass
class EvaluationScores:
    """評価スコア (4観点)。

    Attributes:
        logic: 論理性 (1-5)。
        originality: 独自性 (1-5)。
        constructiveness: 建設性 (1-5)。
        conciseness: 簡潔性 (1-5)。
    """
    logic: int = 0
    originality: int = 0
    constructiveness: int = 0
    conciseness: int = 0

    @property
    def average(self) -> float:
        """4観点の平均値。"""
        scores = [self.logic, self.originality, self.constructiveness, self.conciseness]
        return sum(scores) / len(scores)


@dataclass
class SelfEvaluation:
    """自己評価。

    Attributes:
        role_id: 評価者のロールID。
        scores: 4観点スコア。
        reasoning: 評価理由。
        contribution: 最大の貢献。
        unfinished: やり残し。
    """
    role_id: str
    scores: EvaluationScores
    reasoning: str = ""
    contribution: str = ""
    unfinished: str = ""


@dataclass
class PeerEvaluation:
    """他者評価 (1件)。

    Attributes:
        evaluator_role_id: 評価者のロールID。
        target_role_id: 被評価者のロールID。
        score: 総合スコア (1-5)。
        comment: コメント。
    """
    evaluator_role_id: str
    target_role_id: str
    score: int
    comment: str = ""


@dataclass
class OrchestratorEvaluation:
    """指揮者評価。

    Attributes:
        overall_quality: 全体品質スコア (1-5)。
        mvp_role_id: MVP のロールID。
        mvp_reason: MVP選出理由。
        odsc_achievement: ODSC 達成度 (0.0〜1.0)。
        agent_feedback: 各AIへのフィードバック。
        improvements: 改善提案リスト。
    """
    overall_quality: int = 0
    mvp_role_id: str = ""
    mvp_reason: str = ""
    odsc_achievement: float = 0.0
    agent_feedback: dict[str, str] = field(default_factory=dict)
    improvements: list[str] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """全評価結果の集約。

    Attributes:
        self_evaluations: 自己評価リスト。
        peer_evaluations: 他者評価リスト。
        orchestrator_evaluation: 指揮者評価。
    """
    self_evaluations: list[SelfEvaluation] = field(default_factory=list)
    peer_evaluations: list[PeerEvaluation] = field(default_factory=list)
    orchestrator_evaluation: OrchestratorEvaluation = field(
        default_factory=OrchestratorEvaluation
    )


@dataclass
class Hypothesis:
    """仮説。

    Attributes:
        id: 仮説ID (例: "H1")。
        text: 仮説の内容。
        status: 状態 ("unverified" / "confirmed" / "rejected" / "modified")。
        evidence: 根拠。
        source_round: 生成されたラウンド番号。
    """
    id: str
    text: str
    status: str = "unverified"
    evidence: str = ""
    source_round: int = 0

    STATUS_EMOJI: dict[str, str] = field(default=None, repr=False, init=False)

    def __post_init__(self):
        self.STATUS_EMOJI = {
            "unverified": "🔲",
            "confirmed": "✅",
            "rejected": "❌",
            "modified": "🔄",
        }

    @property
    def status_display(self) -> str:
        """ステータスの絵文字表示。"""
        return self.STATUS_EMOJI.get(self.status, "🔲")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "evidence": self.evidence,
            "source_round": self.source_round,
        }


@dataclass
class SynthesisResult:
    """Phase 3 の統合結果。

    Attributes:
        meta: セッションメタ情報。
        report: レポート Markdown。
        full_conversation: 全会話 Markdown。
        evaluation_md: 評価結果 Markdown。
        summary: 要約テキスト。
        evaluation_result: 構造化された評価結果。
        hypotheses: 抽出された仮説リスト。
        vibe_prompt: (code_review のみ) AIコーディング向け修正指示書。
    """
    meta: dict
    report: str
    full_conversation: str
    evaluation_md: str
    summary: str
    evaluation_result: EvaluationResult
    hypotheses: list[Hypothesis] = field(default_factory=list)
    vibe_prompt: str | None = None
```

### 2.5 Follow-up 関連

```python
@dataclass
class FollowUpContext:
    """フォローアップコンテキスト。

    Attributes:
        previous_session_id: 前セッションのID。
        conclusion: 前セッションの結論。
        hypotheses: 前セッションの仮説リスト。
        unresolved: 未解決の論点リスト。
        compressed_discussion: 圧縮された議論要約。
        previous_agents: 前セッションの参加AI。
        chain_depth: チェーンの深さ。
        focus_hypotheses: 重点検証する仮説ID。
        attachments: 添付ファイル内容。
    """
    previous_session_id: str
    conclusion: str
    hypotheses: list[Hypothesis]
    unresolved: list[str]
    compressed_discussion: str
    previous_agents: list[str]
    chain_depth: int = 1
    focus_hypotheses: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)


@dataclass
class Attachment:
    """添付ファイル情報。

    Attributes:
        filename: ファイル名。
        content: ファイル内容 (切り詰め済み)。
        size_chars: 元の文字数。
        truncated: 切り詰められたか。
    """
    filename: str
    content: str
    size_chars: int
    truncated: bool = False
```

### 2.6 Code Review 関連

```python
@dataclass
class FileInfo:
    """ファイル情報。

    Attributes:
        path: ファイルパス (相対)。
        extension: 拡張子。
        size_bytes: ファイルサイズ。
        lines: 行数。
        header: 先頭部分 (import / class定義等)。
    """
    path: str
    extension: str
    size_bytes: int
    lines: int
    header: str = ""


@dataclass
class ScanResult:
    """フォルダスキャン結果。

    Attributes:
        root_path: スキャン対象のルートパス。
        files: ファイル情報リスト。
        total_files: 総ファイル数。
        total_lines: 総行数。
        languages: 言語別ファイル数。
        tree_text: ツリー表示テキスト。
    """
    root_path: str
    files: list[FileInfo]
    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    tree_text: str = ""


@dataclass
class FileChunk:
    """ファイルの分割チャンク。

    Attributes:
        file_path: 元ファイルパス。
        chunk_index: チャンク番号。
        content: チャンク内容。
        start_line: 開始行番号。
        end_line: 終了行番号。
    """
    file_path: str
    chunk_index: int
    content: str
    start_line: int
    end_line: int


@dataclass
class ReviewFinding:
    """レビュー指摘事項。

    Attributes:
        aspect: 観点 ("algorithm" / "reproducibility" / "performance" / "structure" / "readability" / "results")。
        severity: 深刻度 ("critical" / "major" / "minor" / "suggestion")。
        file_path: 対象ファイルパス。
        line_range: 対象行範囲 (start, end)。
        title: 指摘タイトル。
        description: 指摘詳細。
        suggestion: 修正提案。
    """
    aspect: str
    severity: str
    file_path: str
    line_range: tuple[int, int] | None
    title: str
    description: str
    suggestion: str = ""

    SEVERITY_EMOJI: dict[str, str] = field(default=None, repr=False, init=False)

    def __post_init__(self):
        self.SEVERITY_EMOJI = {
            "critical": "🔴",
            "major": "🟠",
            "minor": "🟡",
            "suggestion": "💡",
        }

    @property
    def severity_display(self) -> str:
        """深刻度の絵文字表示。"""
        return self.SEVERITY_EMOJI.get(self.severity, "💡")

    def to_dict(self) -> dict:
        return {
            "aspect": self.aspect,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_range": self.line_range,
            "title": self.title,
            "description": self.description,
            "suggestion": self.suggestion,
        }


@dataclass
class PartLeaderConfig:
    """パートリーダーの設定。

    Attributes:
        aspect: 担当観点。
        role_id: 使用するロールID。
        files: 担当ファイルリスト。
        focus_prompt: 観点固有の分析プロンプト。
    """
    aspect: str
    role_id: str
    files: list[str]
    focus_prompt: str = ""
```

### 2.7 Feedback 関連

```python
@dataclass
class FeedbackEntry:
    """フィードバック1件。

    Attributes:
        session_id: セッションID。
        date: 実施日。
        topic: 議論テーマ (短縮)。
        self_eval_avg: 自己評価平均。
        peer_eval_avg: 他者評価平均。
        orchestrator_feedback: 指揮者からのフィードバック。
    """
    session_id: str
    date: str
    topic: str
    self_eval_avg: float
    peer_eval_avg: float
    orchestrator_feedback: str


@dataclass
class RoleStats:
    """ロール別統計。

    Attributes:
        role_id: ロールID。
        session_count: 参加セッション数。
        self_eval_avg: 自己評価平均。
        peer_eval_avg: 他者評価平均。
        mvp_count: MVP選出回数。
        trend: トレンド ("improving" / "declining" / "stable")。
        recent_feedback: 直近のフィードバック。
    """
    role_id: str
    session_count: int = 0
    self_eval_avg: float = 0.0
    peer_eval_avg: float = 0.0
    mvp_count: int = 0
    trend: str = "stable"
    recent_feedback: list[str] = field(default_factory=list)
```

### 2.8 TimeKeeper 関連

```python
from enum import Enum


class TimePressure(Enum):
    """時間逼迫度。"""
    RELAXED = "relaxed"
    MODERATE = "moderate"
    URGENT = "urgent"
    CRITICAL = "critical"
```

### 2.9 API Client 関連

```python
@dataclass
class RetryConfig:
    """リトライ設定。

    Attributes:
        max_retries: 最大リトライ回数。
        base_delay_sec: 基本待機時間（秒）。
        max_delay_sec: 最大待機時間（秒）。
        jitter_factor: ジッター係数 (0.0〜1.0)。
    """
    max_retries: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 30.0
    jitter_factor: float = 0.5


@dataclass(frozen=True)
class APIResponse:
    """API レスポンス（不変）。

    Attributes:
        content: 応答テキスト。
        model: 実際に使用されたモデル。
        usage: トークン使用量。
        finish_reason: 終了理由。
    """
    content: str
    model: str
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
```

---

## 3. Web API データモデル (Pydantic)

### 3.1 リクエスト

```python
from pydantic import BaseModel, Field
from typing import Literal


class IdeaPlanRequest(BaseModel):
    """idea 計画立案リクエスト。"""
    prompt: str = Field(..., min_length=5, max_length=5000, description="議論テーマ")
    planner_model: str = Field("gpt-5.4", description="計画立案モデル")
    conductor_model: str = Field("gpt-4.1", description="議論進行モデル")
    synth_model: str = Field("gpt-5.4", description="統合モデル")
    time_limit: int = Field(300, ge=60, le=1800, description="制限時間(秒)")
    max_agents: int = Field(5, ge=2, le=8, description="最大参加AI数")
    expertise: Literal["beginner", "intermediate", "expert"] = Field(
        "intermediate", description="専門レベル"
    )
    follow_up_id: str | None = Field(None, description="フォローアップ元セッションID")
    attached_files: list[str] = Field(default_factory=list, description="添付ファイルパス")


class IdeaStreamRequest(BaseModel):
    """idea ストリーミング実行リクエスト。"""
    plan: dict = Field(..., description="確認済みの計画 (OrchestraPlan.to_dict())")
    prompt: str = Field(..., description="元テーマ")
    conductor_model: str = Field("gpt-4.1", description="議論進行モデル")
    synth_model: str = Field("gpt-5.4", description="統合モデル")
    time_limit: int = Field(300, ge=60, le=1800, description="制限時間(秒)")
    expertise: str = Field("intermediate", description="専門レベル")


class ReviewPlanRequest(BaseModel):
    """review 計画リクエスト。"""
    target_path: str = Field(..., description="レビュー対象ディレクトリパス")
    planner_model: str = Field("gpt-5.4", description="構造判定モデル")
    conductor_model: str = Field("gpt-4.1", description="全体会議モデル")
    synth_model: str = Field("gpt-5.4", description="レポート生成モデル")
    time_limit: int = Field(600, ge=60, le=1800, description="制限時間(秒)")
    max_agents: int = Field(6, ge=2, le=8, description="最大パートリーダー数")
    focus: str = Field("all", description="重点モード")
    ignore_patterns: list[str] = Field(default_factory=list, description="除外パターン")


class SessionListRequest(BaseModel):
    """セッション一覧リクエスト。"""
    type: str | None = Field(None, description="タイプフィルタ (idea/review)")
    search: str | None = Field(None, description="キーワード検索")
    page: int = Field(1, ge=1, description="ページ番号")
    limit: int = Field(10, ge=1, le=50, description="1ページの件数")
```

### 3.2 レスポンス

```python
class IdeaPlanResponse(BaseModel):
    """idea 計画立案レスポンス。"""
    plan: dict
    estimated_requests: int
    remaining_quota: int


class SessionSummary(BaseModel):
    """セッション概要。"""
    id: str
    type: str
    theme: str
    date: str
    duration_sec: float | None = None
    convergence: float | None = None
    focus: str | None = None
    mvp_role_id: str | None = None
    mvp_emoji: str | None = None


class SessionListResponse(BaseModel):
    """セッション一覧レスポンス。"""
    sessions: list[SessionSummary]
    total: int
    page: int
    pages: int


class SessionContentResponse(BaseModel):
    """セッション全コンテンツレスポンス。"""
    session_id: str
    files: dict[str, str]
    statistics: dict
    hypotheses: list[dict] | None = None
    chain: list[str] | None = None


class RoleDetailResponse(BaseModel):
    """ロール詳細レスポンス。"""
    id: str
    name: str
    emoji: str
    specialty: str
    personality: str
    weaknesses: str
    speaking_rules: list[str]
    stats: dict | None = None


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンス。"""
    status: str
    mode: str
    model_available: bool
    rate_limit_remaining: int
    error: str | None = None
```

---

## 4. SSE イベントデータモデル

```python
@dataclass
class SSEEvent:
    """SSEイベントの基底。"""
    type: str

    def to_json(self) -> str:
        """JSON文字列に変換する。"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_dict(self) -> dict:
        return {"type": self.type}


@dataclass
class PlanningStartEvent(SSEEvent):
    """計画立案開始。"""
    type: str = "planning_start"


@dataclass
class PlanningCompleteEvent(SSEEvent):
    """計画立案完了。"""
    type: str = "planning_complete"
    plan: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "plan": self.plan}


@dataclass
class RoundStartEvent(SSEEvent):
    """ラウンド開始。"""
    type: str = "round_start"
    round: int = 0
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "round": self.round, "config": self.config}


@dataclass
class UtteranceEvent(SSEEvent):
    """発言イベント。"""
    type: str = "utterance"
    round: int = 0
    agent: dict = field(default_factory=dict)
    content: str = ""
    tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "round": self.round,
            "agent": self.agent,
            "content": self.content,
            "tokens": self.tokens,
        }


@dataclass
class RoundConclusionEvent(SSEEvent):
    """ラウンド結論。"""
    type: str = "round_conclusion"
    round: int = 0
    concluder: str = ""
    content: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "round": self.round,
            "concluder": self.concluder,
            "content": self.content,
        }


@dataclass
class RoundEndEvent(SSEEvent):
    """ラウンド終了。"""
    type: str = "round_end"
    round: int = 0
    convergence: float = 0.0
    elapsed_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "round": self.round,
            "convergence": self.convergence,
            "elapsed_sec": self.elapsed_sec,
        }


@dataclass
class ProgressEvent(SSEEvent):
    """進捗イベント。"""
    type: str = "progress"
    phase: str = ""
    percent: int = 0
    elapsed_sec: float = 0.0
    remaining_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "phase": self.phase,
            "percent": self.percent,
            "elapsed_sec": self.elapsed_sec,
            "remaining_sec": self.remaining_sec,
        }


@dataclass
class TimePressureEvent(SSEEvent):
    """時間逼迫イベント。"""
    type: str = "time_pressure"
    remaining_sec: float = 0.0
    pressure: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "remaining_sec": self.remaining_sec,
            "pressure": self.pressure,
        }


@dataclass
class DoneEvent(SSEEvent):
    """完了イベント。"""
    type: str = "done"
    session_id: str = ""
    output_dir: str = ""
    statistics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "output_dir": self.output_dir,
            "statistics": self.statistics,
        }


@dataclass
class ErrorEvent(SSEEvent):
    """エラーイベント。"""
    type: str = "error"
    message: str = ""
    recoverable: bool = False

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            "recoverable": self.recoverable,
        }
```

---

## 5. 設定データモデル

```python
@dataclass
class APISettings:
    """API接続設定。"""
    key: str = ""
    endpoint: str = ""
    mode: str = ""
    daily_limit: int = 10000
    safety_margin: float = 0.9


@dataclass
class TimeoutSettings:
    """モデル別タイムアウト。"""
    defaults: dict[str, int] = field(default_factory=lambda: {
        "gpt-5.4": 120,
        "gpt-4.1": 90,
        "gpt-4.1-mini": 60,
        "gpt-4.1-nano": 30,
        "default": 90,
    })

    def get(self, model: str) -> int:
        """モデル別タイムアウトを取得する。"""
        return self.defaults.get(model, self.defaults["default"])


@dataclass
class DiscussionSettings:
    """議論関連設定。"""
    time_limit_default: int = 300
    time_limit_min: int = 60
    time_limit_max: int = 1800
    max_agents_default: int = 5
    max_agents_min: int = 2
    max_agents_max: int = 8
    convergence_threshold: float = 0.85
    stagnation_window: int = 3
    utterance_min_chars: int = 50
    utterance_max_chars: int = 150
    utterance_absolute_max_chars: int = 200


@dataclass
class FeedbackSettings:
    """フィードバック設定。"""
    max_history: int = 10
    trend_window: int = 3
    reinforcement_threshold: float = 3.0


@dataclass
class Settings:
    """全体設定。"""
    api: APISettings = field(default_factory=APISettings)
    timeout: TimeoutSettings = field(default_factory=TimeoutSettings)
    discussion: DiscussionSettings = field(default_factory=DiscussionSettings)
    feedback: FeedbackSettings = field(default_factory=FeedbackSettings)
    output_dir: str = "./output"
    roles_dir: str = "./config/roles"
    scenarios_dir: str = "./config/scenarios"
```

---

## 6. 出力ファイル形式

### 6.1 session_meta.json

```json
{
  "session_id": "20260622_133204_idea",
  "type": "idea",
  "theme": "LLMの推論効率を改善する手法を議論して",
  "created_at": "2026-06-22T13:32:04",
  "duration_sec": 272.5,
  "parameters": {
    "planner_model": "gpt-5.4",
    "conductor_model": "gpt-4.1",
    "synth_model": "gpt-5.4",
    "time_limit": 300,
    "max_agents": 5,
    "expertise": "intermediate"
  },
  "agents": ["theorist", "experimentalist", "implementer", "literature", "devil"],
  "statistics": {
    "total_requests": 36,
    "total_tokens": 12500,
    "total_utterances": 14,
    "rounds_completed": 3,
    "final_convergence": 0.87,
    "mvp": "theorist"
  },
  "follow_up": {
    "previous_session_id": null,
    "chain_depth": 0
  }
}
```

### 6.2 discussion.json

```json
{
  "plan": { "...OrchestraPlan.to_dict()..." },
  "rounds": [
    {
      "round_num": 1,
      "config": { "...RoundConfig.to_dict()..." },
      "utterances": [
        {
          "role_id": "theorist",
          "role_name": "理論屋",
          "emoji": "🧮",
          "content": "計算量の観点から見ると...",
          "round_num": 1,
          "tokens": 150,
          "duration_sec": 3.2,
          "timestamp": "2026-06-22T13:33:15"
        }
      ],
      "conclusion": "KV-cache圧縮が...",
      "concluder_role_id": "theorist",
      "convergence_score": 0.72,
      "duration_sec": 45.2,
      "total_tokens": 850
    }
  ],
  "evaluations": {
    "self": [ "...SelfEvaluation..." ],
    "peer": [ "...PeerEvaluation..." ],
    "orchestrator": { "...OrchestratorEvaluation..." }
  },
  "total_duration_sec": 272.5,
  "total_tokens": 12500
}
```

---

## 7. 型の使い分けガイド

| シーン | 使う型 | 理由 |
|--------|--------|------|
| モジュール間のデータ受け渡し | `@dataclass` | 型安全、IDE補完 |
| Web API リクエスト/レスポンス | `BaseModel` (Pydantic) | バリデーション自動化 |
| JSON 出力 | `.to_dict()` → `json.dumps()` | 明示的な変換 |
| 設定ファイル読み込み | `@dataclass` + `classmethod` | デフォルト値管理 |
| 列挙値 | `Enum` | 型安全、補完 |
| 不変データ | `@dataclass(frozen=True)` | 意図しない変更防止 |
| 一時的な内部データ | `dict` (OK) | 外に出さない短命データ |

---

## 8. import ガイド

```python
# データモデルの import パターン

# core/ 内から使う場合
from core.orchestrator import OrchestraPlan, ODSC, RoundConfig, DiscussionPlan
from core.conductor import DiscussionLog, RoundLog, ConvergenceResult
from core.agent import AgentConfig, Utterance
from core.synthesizer import SynthesisResult, EvaluationResult
from core.follow_up import FollowUpContext
from core.feedback import FeedbackEntry, RoleStats
from core.time_keeper import TimePressure
from core.api_client import RetryConfig, APIResponse

# web/ から使う場合 (Pydantic モデル)
from web.routes.api_idea import IdeaPlanRequest, IdeaStreamRequest, IdeaPlanResponse
from web.routes.api_sessions import SessionListResponse, SessionContentResponse
