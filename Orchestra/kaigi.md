# Orchestra 会議システム実装概要

> 本ドキュメントは Orchestra プロジェクトの「会議 (kaigi = meeting/discussion)」システムの現状実装を、外部の LLM (Claude) に改善プロンプトを作成させるための下地資料として整理したものです。

---

## 1. システム全体像

### 1.1 3 フェーズ構成

Orchestra は全ての処理を **3 つのフェーズ**に分離します。各フェーズは独立した目的と LLM を持ちます。

| フェーズ | 名称 | 担当モデル | 役割 | 所要時間 |
|---------|------|----------|------|---------|
| Phase 1 | 計画立案 (Planning) | ``gpt-5.4`` (reasoning_effort=high) | ユーザー入力から ODSC・参加 AI を決定し、ラウンド構成を設計 | ~4 秒 |
| Phase 2 | 議論進行 (Discussion) | 軽量モデル (``gpt-4.1``) / エージェント別 | Conductor が指揮者として議論の流れを制御・進行管理 | ~180 秒 |
| Phase 3 | 統合・評価 (Synthesis) | ``claude-sonnet-4-5`` (extended thinking) | 全 AI の評価取得・レポート生成・ODSC 達成度判定 | ~25 秒 |

### 1.2 2 つの機能フロー

**機能①: IdeaDiscussion (アイデア議論)**
- エントリポイント: [misc_26/Orchestra/features/idea_discussion.py](misc_26/Orchestra/features/idea_discussion.py)
- ユーザーのテーマに対して多視点から技術的アイデアを膨らませる
- 合意形成ではなく「深化」を目指す (早期終了は時間制限まで無効化)
- 7 つの出力ファイル (JSON + MD + TXT) を生成

**機能②: CodeReview (コードレビュー)**
- エントリポイント: [misc_26/Orchestra/features/code_review/code_review.py](misc_26/Orchestra/features/code_review/code_review.py)
- 5 つの Phase (スキャン → 個別調査 → 相互質問 → 全体会議 → レポート) で code を多角分析
- 6 パートリーダー (アルゴリズム・再現性・パフォーマンス・構造・可読性・結果) で同時並行調査

### 1.3 主要コンポーネント

```
IdeaDiscussion / CodeReview (entry)
   ├─ Orchestrator (Phase 1)       ← 計画立案 LLM
   │  └─ OrchestraPlan 出力
   │
   ├─ Agent * N (Phase 2)           ← 発言を生成する AI
   │
   ├─ Conductor (Phase 2)           ← 進行管理 LLM
   │  ├─ ConvergenceChecker / RepetitionDetector / AgreementDetector
   │  ├─ Speaking Order Strategy (Fixed / Dialectic / Shuffle / Dynamic)
   │  ├─ TimeKeeper                ← 時間圧力管理
   │  └─ ConversationMemory        ← 全発言ログと要約
   │
   ├─ Synthesizer (Phase 3)        ← 評価統合 LLM
   │  └─ SynthesisResult 出力
   │
   └─ OutputGenerator              ← ファイル書き出し
```

---

## 2. 会議の設計単位

### 2.1 ODSC (Objective / Deliverable / Success Criteria / Convergence threshold)

会議のゴール定義。Orchestrator が生成し、全フェーズで参照されます。

```python
@dataclass
class ODSC:
    objective: str          # 「何を達成するのか」 (1 文)
    deliverable: str        # 成果物の形式
    success_criteria: str   # 成功の基準
    convergence_threshold: float  # 0.0-1.0 (デフォルト 0.85)
```

### 2.2 OrchestraPlan (Phase 1 出力)

Orchestrator が返す完全な実行計画。

```python
@dataclass
class OrchestraPlan:
    odsc: ODSC
    selected_agents: list[AgentConfig]           # 参加 AI (role_id, model, level, reason)
    discussion_plan: DiscussionPlan | None       # ラウンド構成
    private_instructions: dict[str, PrivateInstruction]  # 各 AI への個別指示
```

### 2.3 DiscussionPlan (ラウンド構成)

議論を何ラウンドに分割するか、各ラウンドの目標・パターン・時間予算を定義。

```python
@dataclass
class DiscussionPlan:
    estimated_rounds: int
    round_config: list[RoundConfig]
    total_estimated_time_sec: float
    total_estimated_requests: int
```

### 2.4 RoundConfig (1 ラウンドの実行設定)

```python
@dataclass
class RoundConfig:
    round: int                  # ラウンド番号 (1-indexed)
    phase_name: str             # 名称 (例: 「問題の定式化」)
    speakers: list[str]         # 発言する role_id リスト
    pattern: str                # "one_shot" / "ping_pong" / "free_talk"
    level: str                  # "minimal" / "low" / "medium" / "high"
    time_budget_sec: float
    goal: str                   # ラウンドの到達目標
```

### 2.5 PrivateInstruction (各 AI への個別指示)

Orchestrator が各エージェントの役割・期待・制約を明記。ラウンド開始時に system prompt に注入されます。

```python
@dataclass
class PrivateInstruction:
    role_id: str
    expected_contribution: str      # このラウンドでの期待
    focus_points: list[str]         # 注視すべき観点
    constraints: list[str]          # やってはいけないこと
    context_from_plan: str          # 議論計画上の位置づけ
    feedback_reminder: str          # 過去フィードバックからの改善依頼
    speaking_rules: str             # 発言形式のルール
```

---

## 3. 発話パターン (RoundConfig.pattern)

Conductor が採用する 3 つの基本パターン。設計書に基づき Orchestrator が選択、LLM が返した異名は ``_PATTERN_ALIASES`` で正規化されます。

| パターン | 発言順序 | 最大発言数 | 用途 | 時間目安 |
|---------|-------|---------|------|--------|
| **one_shot** | 計画順 (固定) | speakers 数 | 発散・全員一周・アイデア出し | 短い |
| **ping_pong** | 対立ペア交互 | min(N×2, 6) | 反論・深掘り・議論白熱化 | 中程度 |
| **free_talk** | Conductor が動的決定 | min(N×3, 8) | 創発・自由な発言・流動的議論 | 長い |

### 3.1 発言順序戦略 (Speaking Order)

[misc_26/Orchestra/core/speaking_order.py](misc_26/Orchestra/core/speaking_order.py) で実装。

- **FixedOrder**: ``round_config.speakers`` をそのまま使用
- **DialecticOrder**: 対立関係にあるペアを交互配置 (例: theorist ↔ devil)
- **ShuffleOrder**: ランダム順
- **DynamicOrder**: 直前発言の内容を LLM が読み、最適な次発言者を決定 (free_talk 用、``gpt-4.1`` 軽量呼び出し)

---

## 4. ラウンドと収束

### 4.1 ラウンドの進行フロー

```
Round Start
  ├─ [Conductor] 目標・パターン・個別指示を各 AI に提示
  │
  ├─ Utterance Loop (パターン依存)
  │  ├─ FixedOrder / DialecticOrder: 順序確定 → 順番に Agent.speak()
  │  └─ free_talk: 各発言後、DynamicOrder で次人を決定
  │  └─ [各 Agent] System Prompt + Context を統合し API 呼び出し → Utterance
  │  └─ [ConversationMemory] 発言をログ・トークン集計
  │
  ├─ Round Conclusion (パターン/設定による)
  │  └─ ラウンドリーダーが「結論」発言を追加 (ラウンド内容の統合・整理)
  │
  ├─ [Conductor] 収束判定 (ラウンド終了後)
  │  ├─ ConvergenceChecker: スコア 0.0-1.0 を判定
  │  ├─ RepetitionDetector: 堂々巡り警告
  │  └─ AgreementDetector: 同意しすぎる場合に異議申し立て指示
  │
  └─ [Conductor] 時間圧力チェック → 次ラウンド開始判断
```

### 4.2 ConvergenceResult (収束判定結果)

[misc_26/Orchestra/core/convergence.py](misc_26/Orchestra/core/convergence.py) で ``gpt-4.1`` が非同期実行。

```python
@dataclass
class ConvergenceResult:
    score: float                        # 0.0-1.0 の収束度
    reasoning: str                      # 1-2 文の根拠
    remaining_disagreements: list[str]  # 未解決の論点
    recommendation: str                 # "continue" / "conclude" / "pivot"
```

**score の目安**:
- 0.0-0.3: 方向性すら定まっていない
- 0.3-0.5: 方向性は見えるが広がり不足
- 0.5-0.65: 複数の切り口が出たが深掘り不足
- 0.65-0.8: 主要方向が探索され、具体的アクションも一部
- 0.8-0.9: アイデアが十分に発展
- 0.9-1.0: 完全に議論し尽くした (稀)

### 4.3 Early Termination (早期終了)

```python
early_termination: str | None  # None / "converged" / "time_limit" / "force"
termination_detail: str        # 理由の詳細
score_history: list[float]     # 各ラウンド終了時のスコア推移
```

現状仕様:
- **時間制限優先**: 収束スコアが高くても時間が尽きるまで議論継続
- **早期収束は無効化**: ``run_discussion`` で ``score_history`` は記録するが、スコアが高くてもラウンドは実行
- **Pivot 指示**: スコアが停滞 (``stagnation_window=3`` 内で変動 < ``stagnation_tolerance=0.05``) した場合、Conductor が次ラウンドに「方向転換」指示を注入

---

## 5. 発話生成 (Agent + Conductor)

### 5.1 Agent.speak() のシグネチャと流れ

[misc_26/Orchestra/core/agent.py](misc_26/Orchestra/core/agent.py) の主要メソッド。

```python
async def speak(
    self,
    round_context: dict[str, Any],
    additional_instruction: str = ""
) -> Utterance:
    """1 発言を生成し Utterance を返す"""

    # 1. システムプロンプト構築
    #    ロール定義 YAML のテンプレート + orchestrator_instruction
    #    + feedback_context + speaking_rules

    # 2. ユーザーメッセージ構築 (Layer 2-6 のコンテキストを統合)
    #    Layer 2: Orchestrator メモ
    #    Layer 3: 過去ラウンド要約
    #    Layer 4: 直近全発言
    #    Layer 5: 追加指示 (堂々巡り時など)
    #    Layer 6: ODSC 再掲

    # 3. API パラメータ構築 (モデル別)
    #    標準: temperature=0.7, max_tokens=300
    #    Claude thinking: reasoning_effort に応じた max_tokens + budget
    #    GPT-5: verbosity="low" 指定

    # 4. API 呼び出し

    # 5. 発言長チェック (3 段防衛)
    #    len(content) > MAX_UTTERANCE_CHARS (200) の場合、
    #    gpt-4.1 で短縮を要求

    # 6. Utterance を返す
```

### 5.2 ConversationMemory のコンテキスト提供

[misc_26/Orchestra/core/memory.py](misc_26/Orchestra/core/memory.py) の ``get_context_for_agent()`` メソッド。

- **Token 予算管理**: モデル別入力上限 - level 別出力予約 = 実効上限
- **Layer 構成**:
  - ``previous_summary`` — Layer 3: 前ラウンド要約
  - ``current_round_utterances`` — Layer 4: このラウンド全発言
  - ``last_utterance`` — 直前発言の参考
  - ``system_events`` — 堂々巡り検知など
  - ``odsc`` — ゴール定義
  - ``round_goal`` — このラウンドの目標
  - ``next_sequence`` — 次の発言番号
- **オーバー時**: Layer 3 (過去要約) を先頭 30% だけ残して圧縮

**Token 推定式**:
```
日本語 1 文字 ≈ 1.5 token
英語 1 文字 ≈ 0.3 token
```

### 5.3 Conductor が集約する情報

Conductor が各 AI に渡す **round_context** は以下で構成。

| キー | 由来 | 内容 |
|-----|------|------|
| ``odsc`` | Plan | 議論のゴール定義 |
| ``round_goal`` | RoundConfig | このラウンドの目標 |
| ``private_instruction`` | PrivateInstruction | 各 AI への個別指示 |
| ``previous_summary`` | ConversationMemory | 前ラウンドの要約 |
| ``utterances`` | ConversationMemory | このラウンドの全発言 |
| ``next_sequence`` | Conductor 計算 | 次の sequence 番号 |

---

## 6. Idea Discussion 固有

### 6.1 エントリポイント: IdeaDiscussion.run()

[misc_26/Orchestra/features/idea_discussion.py](misc_26/Orchestra/features/idea_discussion.py)

```python
async def run(
    user_input: str,
    planner_model: str = "gpt-5.4",
    conductor_model: str = "gpt-4.1",
    synth_model: str = "claude-sonnet-4-5",
    time_limit: float = 300,
    max_agents: int = 5,
    expertise: str = "intermediate",    # "beginner" / "intermediate" / "expert"
    follow_up_id: str | None = None,
    attached_files: list[Path] | None = None,
    focus_hypotheses: list[str] | None = None,
    output_dir: Path | None = None,
    on_phase: Callable[[str], None] | None = None,
    intervention: InterventionHandler | None = None
) -> Path | None:
    """完全な議論フローを実行し、セッションディレクトリパスを返す"""
```

**追加**: 復元用に `run_from_plan(user_input, plan, ...)` を用意しており、Phase 1 をスキップして既存 OrchestraPlan から直接 Phase 2 を開始できる (履歴の「編集して再実行」フローで使用)。

### 6.2 フロー

```
1. Input Validation
   - user_input: 5-5000 文字チェック
   - attached_files: 最大 5 個、合計 10000 文字以下

2. Phase 1: 計画立案
   - Orchestrator.plan() で OrchestraPlan を生成
   - ユーザー確認 (confirm_callback)

3. Phase 2: 議論進行
   - Conductor.run_discussion() で全ラウンド実行
   - SSE イベント配信 (Web UI 用)

4. Phase 3: 統合・評価
   - Synthesizer.synthesize() で全評価取得 + レポート生成

5. 出力ファイル生成
   - OutputGenerator.generate() で 7 種ファイル作成
   - FeedbackManager でロール YAML 更新

6. Follow-up チェーン管理
   - FollowUpContext を構築して過去セッション情報を引き継ぎ
```

### 6.3 シナリオ自動検出

[misc_26/Orchestra/features/idea_discussion.py](misc_26/Orchestra/features/idea_discussion.py) の `SCENARIO_KEYWORDS`。

```python
SCENARIO_KEYWORDS: dict[str, tuple[str, ...]] = {
    "algorithm_design":    ("設計", "アルゴリズム", "手法", "アプローチ", "方式"),
    "experiment_planning": ("実験", "検証", "比較", "ベンチマーク", "評価"),
    "paper_discussion":    ("論文", "paper", "手法の理解", "読み会", "サーベイ"),
}
```

ユーザー入力にこれらキーワードが含まれると、対応するシナリオテンプレートが自動選定され、Orchestrator プロンプトに注入されます。

---

## 7. Code Review 固有

### 7.1 Phase 構成

[misc_26/Orchestra/features/code_review/code_review.py](misc_26/Orchestra/features/code_review/code_review.py)

| Phase | 名称 | 責務 |
|-------|------|------|
| Phase 1 | スキャン | 対象フォルダの全ファイル情報を収集 (LLM 不使用) |
| Phase 2 | 個別調査 | 6 パートリーダーが並行してファイル分析し findings 抽出 |
| Phase 3 | 相互質問 | CrossQuestioner が各 concern の findings に関連質問を追加 |
| Phase 4 | 全体会議 | 各パートリーダーが Agent として議論。優先度・修正順序を決定 |
| Phase 5 | レポート生成 | findings + 議論結果をレポート形式で出力 |

### 7.2 6 パートリーダーと focus

[misc_26/Orchestra/features/code_review/constants.py](misc_26/Orchestra/features/code_review/constants.py)

```python
FOCUS_PRESETS = {
    "all": {
        "algorithm": 1.0, "reproducibility": 1.0, "performance": 1.0,
        "structure": 1.0, "readability": 1.0, "results": 1.0,
    },
    "pre_submission": { "algorithm": 2.0, "reproducibility": 2.0, ... },
    "performance":    { "performance": 2.0, ... },
    # 他: structure / handover / algorithm
}
```

各パートリーダーに割り当てられるファイルは `PartLeaderAssigner` が算出。

```python
@dataclass
class PartLeaderConfig:
    concern: str                   # 観点名
    weight: float                  # focus から算出される重み
    assigned_files: list[str]      # 責任ファイルリスト
    role_id: str                   # CONCERN_TO_ROLE で解決
    model: str                     # CONCERN_TO_MODEL で解決
    level: str                     # weight から "low" / "medium" / "high" に昇格
```

### 7.3 MeetingPhase (Phase 4)

[misc_26/Orchestra/features/code_review/meeting.py](misc_26/Orchestra/features/code_review/meeting.py)

Phase 4 全体会議は通常の Idea Discussion と同じ Conductor ロジックを使用。ただし発言ルールと 3 ラウンド構成は固定:

```
MEETING_SPEAKING_RULES:
- 1 発言 50〜150 文字。チャットの会話テンポで。
- 他者の発言に対して「同意するだけ」は禁止。必ず新情報か反論を 1 つ追加。
- Round 2 では必ず 1 回は他者の意見に反論する。
- 具体的なファイル名・行番号を出す。抽象論禁止。
- 「たしかに」から始めるのは 2 回に 1 回まで。

Round 構成:
  Round 1: phase_name="課題報告と問題提起"  pattern="one_shot"  time=60s
  Round 2: phase_name="深掘りと反論"        pattern="free_talk" time=120s max=8
  Round 3: phase_name="合意形成"            pattern="one_shot"  time=60s
```

### 7.4 Investigator (Phase 2)

[misc_26/Orchestra/features/code_review/investigator.py](misc_26/Orchestra/features/code_review/investigator.py)

1 パートリーダーごとに並行実行。

```python
async def investigate_one_leader(
    api_client, chunker, scan_result, leader
) -> list[dict[str, Any]]:
    """
    1. 担当ファイルを結合 (max 60000 chars)
    2. concern 専用プロンプトを構築
    3. LLM で findings を JSON 抽出
    4. LLM 失敗時は空リスト返却 (全体を止めない)
    """
```

出力 findings 構造:

```json
{
  "findings": [
    {
      "file": "src/main.py",
      "line": 123,
      "severity": "high" | "medium" | "low",
      "issue": "具体的な問題指摘",
      "suggestion": "改善提案"
    }
  ]
}
```

### 7.5 CrossQuestioner (Phase 3)

[misc_26/Orchestra/features/code_review/cross_question.py](misc_26/Orchestra/features/code_review/cross_question.py)

各 concern の findings に対して「なぜそうなるのか」「代替案は」といった質問を LLM で追加生成。findings を補強します。

---

## 8. 時間管理と介入

### 8.1 TimeKeeper (時間圧力管理)

[misc_26/Orchestra/core/time_keeper.py](misc_26/Orchestra/core/time_keeper.py)

```python
@dataclass
class TimeKeeper:
    time_limit_sec: float
    phase1_actual_sec: float       # Phase 1 実測
    phase3_reserve_sec: float      # Phase 3 用確保 (デフォルト 25 秒)
    safety_margin: float           # 0.9 (時間上限の 90% を実効とする)

    @property
    def discussion_budget(self) -> float:
        return time_limit_sec * safety_margin - phase1_actual_sec - phase3_reserve_sec

    @property
    def remaining(self) -> float:
        return max(0.0, discussion_budget - discussion_elapsed)

    @property
    def pressure(self) -> TimePressure:
        # RELAXED (>50%) / MODERATE (20-50%) / URGENT (5-20%) / CRITICAL (<5%)
```

### 8.2 TimePressure と Conductor の応答

```python
async def _handle_time_pressure(self, estimated: float) -> str:
    pressure = self.time_keeper.pressure
    remaining = self.time_keeper.remaining

    if remaining < FORCE_CONCLUDE_THRESHOLD_SEC (5 秒):
        return "terminate"          # 残り 5 秒未満 → 強制終了

    if pressure == TimePressure.CRITICAL:
        return "downgrade_level"    # level 低減: high → medium → low → minimal

    if pressure == TimePressure.URGENT:
        return "reduce_speakers"    # speakers 数削減

    return "continue"
```

### 8.3 TurnCalculator (所要時間推定)

[misc_26/Orchestra/core/turn_calculator.py](misc_26/Orchestra/core/turn_calculator.py)

```python
LEVEL_TIME_MAP = {"minimal": 3.0, "low": 5.0, "medium": 10.0, "high": 20.0}
utterances = {
    "one_shot":  len(speakers),
    "ping_pong": min(len(speakers) * 2, 6),
    "free_talk": min(len(speakers) * 3, 8),
}[pattern]
round_time = utterances * LEVEL_TIME_MAP[level] + CONDUCTOR_OVERHEAD + CONVERGENCE_CHECK_TIME
```

### 8.4 Intervention (ユーザー介入)

[misc_26/Orchestra/core/intervention.py](misc_26/Orchestra/core/intervention.py) — 抽象インターフェース。v1.0 では `NoIntervention` のみ提供。

```python
class InterventionHandler(ABC):
    def check_intervention(self, round_num: int, context: dict) -> str | None:
        """ラウンド間で人間からの指示を確認。None = 介入なし"""

    def notify_progress(self, event: str, data: dict) -> None:
        """進捗イベントを通知 (UI 更新用)"""
```

**SSEInterventionHandler**: Web UI 向け SSE 配信用。`asyncio.Queue` に進捗イベントを put し、Web エンドポイントが queue から read して SSE stream に流す。

---

## 9. SSE イベントスキーマ

[misc_26/Orchestra/web/routes/api_idea.py](misc_26/Orchestra/web/routes/api_idea.py) と [misc_26/Orchestra/web/static/js/sse.js](misc_26/Orchestra/web/static/js/sse.js)

Conductor が `intervention.notify_progress(event, data)` で発火するイベント。

| イベント名 | payload | 説明 |
|-----------|---------|------|
| `progress` | `{total_rounds, remaining_sec}` | 議論開始時に全ラウンド数を通知 |
| `phase_start` | `{phase: "planning"|"discussion"|"synthesis"}` | フェーズ開始 |
| `planning` | `{model, duration_sec}` | Phase 1 完了 |
| `round_start` | `{round, phase_name, goal, pattern, config}` | ラウンド開始 |
| `utterance` | `{agent: {emoji, name}, content, round, tokens, duration_sec}` | AI 発言 |
| `round_conclusion` | `{round, conclusion}` | ラウンド結論 |
| `convergence_check` | `{score, recommendation, reasoning}` | 収束判定結果 |
| `round_end` | `{round, duration_sec, convergence}` | ラウンド終了 |
| `synthesis_start` | `{}` | Phase 3 開始 |
| `done` | `{session_id, output_dir, final_convergence, total_tokens, files?}` | 全完了 |
| `error` | `{message, code, recoverable}` | エラー発生 |

**Code Review 固有イベント**:

| イベント名 | payload |
|-----------|---------|
| `scan_start` / `scan_complete` | `{scan_result}` |
| `investigation_start` | `{aspect, emoji}` |
| `investigation_progress` | `{aspect, progress, current, total}` |
| `investigation_finding` | `{aspect, finding}` |
| `investigation_complete` | `{aspect, findings_count}` |
| `cross_question_start` / `cross_question_complete` | — |
| `cross_question` | `{questioner, target, question}` |
| `cross_answer` | `{answerer, questioner, answer}` |
| `meeting_start` | — |

フロント側 (`OrchestraSSE` クラス) が各イベントを subscribe し、`this._dispatch(type, data)` 経由で UI 更新関数へ配信。

---

## 10. 出力ファイル

[misc_26/Orchestra/core/output_generator.py](misc_26/Orchestra/core/output_generator.py) で生成。セッションディレクトリ `output/{session_id}/` 以下に 7 ファイル。

| # | ファイル名 | 形式 | 内容 |
|---|-----------|------|------|
| 1 | `session_meta.json` | JSON | 検索・一覧用メタデータ (軽量) |
| 2 | `discussion.json` | JSON | 完全ログ (機械処理・再現用) |
| 3 | `full_conversation.md` | Markdown | 全会話台本 (人間が読む) |
| 4 | `report.md` | Markdown | 最終レポート (結論・洞察) |
| 5 | `evaluation.md` | Markdown | 評価詳細 (自己/他者/指揮者) |
| 6 | `summary.txt` | テキスト | 1 ページ要約 (共有用) |
| 7 | `vibe_coding_prompt.md` | Markdown | AI 修正指示書 (機能②のみ) |

### 10.1 session_meta.json

軽量メタデータ。過去セッション検索・follow-up チェーン管理用。

```json
{
  "_schema_version": "1.0.0",
  "session_id": "20260620_143052_idea",
  "type": "idea_discussion",
  "status": "completed",
  "created_at": "...",
  "completed_at": "...",
  "duration_sec": 216,
  "user_prompt": "テーマ",
  "expertise": "intermediate",
  "models_used": ["gpt-5.4", "claude-sonnet-4-5", "gpt-4.1"],
  "agents_used": ["theorist", "experimentalist", "implementer"],
  "total_rounds": 5,
  "final_convergence": 0.88,
  "total_requests": 35,
  "follow_up": {
    "is_follow_up": false,
    "parent_session_id": null,
    "chain_depth": 0,
    "chain": ["20260620_143052_idea"]
  },
  "evaluation_summary": {
    "overall_quality": 4.2,
    "mvp": "theorist",
    "avg_self_score": 4.0,
    "avg_peer_score": 4.1
  },
  "output_files": { ... }
}
```

### 10.2 discussion.json (完全ログ、履歴復元にも使用)

```json
{
  "_schema_version": "1.0.0",
  "session": { ... },
  "planning": {
    "odsc": { ... },
    "selected_agents": [ ... ],
    "discussion_plan": { ... },
    "private_instructions": { role_id: PrivateInstruction }
  },
  "discussion": {
    "rounds": [
      {
        "round": 1,
        "phase_name": "問題の定式化",
        "goal": "...",
        "duration_sec": 43,
        "public_utterances": [
          {
            "speaker": "theorist",
            "content": "...",
            "tokens_used": {"input": ..., "output": ...},
            "duration_sec": 2.1,
            "reasoning_content": "..."   // Claude thinking の場合
          }
        ],
        "convergence_check": {
          "score": 0.75,
          "reasoning": "...",
          "recommendation": "continue"
        }
      }
    ],
    "final_convergence_score": 0.88,
    "early_termination": null,
    "score_history": [0.3, 0.5, 0.65, 0.78, 0.88]
  },
  "evaluation": { role_id: {self_evaluation, peer_evaluations} },
  "orchestrator_evaluation": { ... }
}
```

**追加**: Code Review mock セッションではさらに `review_context` (target_path, focus, scan_result, part_leaders, findings_by_aspect, cross_qa) を含めており、Web UI の「編集して再実行」時にこの JSON から各ステップ状態を復元する。

---

## 11. 現在確認されている設計特性・制約

### 11.1 コア仕様

- **時間優先設計**: Phase 2 は収束スコアではなく時間制限まで継続 (早期終了機能は無効化)
- **LLM 障害耐性**: 1 つのエージェント/パートリーダー/検知器の失敗が全体フローを止めない (空結果返却)
- **Token 効率**: ConversationMemory が過去要約で Layer 3 を削るなど、コンテキスト圧縮
- **Pivot 指示**: 停滞検知時 (スコア変動 < 0.05 が 3 ラウンド連続) に Conductor が次ラウンドに「方向転換」指示を注入

### 11.2 既知のハードコード / マジックナンバー

[misc_26/Orchestra/core/conductor.py](misc_26/Orchestra/core/conductor.py):
```python
PING_PONG_DEFAULT_EXCHANGES = 3
FREE_TALK_DEFAULT_MAX = 8
FREE_TALK_REPETITION_CHECK_INTERVAL = 4
CONSECUTIVE_SAME_SPEAKER_LIMIT = 2
```

[misc_26/Orchestra/core/memory.py](misc_26/Orchestra/core/memory.py):
```python
JP_TOKEN_PER_CHAR = 1.5
EN_TOKEN_PER_CHAR = 0.3
TRUNCATE_TAIL_RATIO = 0.3
```

[misc_26/Orchestra/core/convergence.py](misc_26/Orchestra/core/convergence.py):
```python
DEFAULT_STAGNATION_WINDOW = 3
DEFAULT_STAGNATION_TOLERANCE = 0.05
DEFAULT_REPETITION_WINDOW = 4
DEFAULT_AGREEMENT_WINDOW = 3
```

### 11.3 設定ファイル体系

[misc_26/Orchestra/config/settings.yaml](misc_26/Orchestra/config/settings.yaml):
- 時間設定 (Phase 別予約、制限値)
- エージェント数制限
- 収束閾値
- 会話スタイル (brainstorming / lab_discussion / formal / casual / debate)
- 発言長制限 (min 50 / max 200 chars)
- ラウンド内発言制限 (one_shot / ping_pong / free_talk 別)

[misc_26/Orchestra/config/roles/](misc_26/Orchestra/config/roles/) `*.yaml`:
- 各ロール定義 (display_name, model, personality, expertise, domain_tags, evaluation_criteria, system_prompt_template)
- Agent が読み込み、指揮者指示でカスタマイズ

### 11.4 未実装 / 将来予定

[misc_26/Orchestra/doc/design/](misc_26/Orchestra/doc/design/) の各ドキュメントに記載:
- Phase F (Follow-up Manager): セッションチェーンと履歴管理
- CLI 介入ハンドラ (`CLIIntervention`): ユーザー対話
- WebSocket 介入ハンドラ (`WebIntervention`): 同期制御
- エージェント別コンテキスト最適化 (現状は全エージェント共通 context)
- Phase 1 での機能グループ推定 (Code Review)

### 11.5 現状の主な違和感 / 論点候補

改善プロンプト設計時のヒント:

1. **早期終了無効化のトレードオフ** — 時間制限まで議論継続することで、既に収束した議題でも延々と発言が続くケースがある
2. **`convergence_check` が結果に反映されない** — スコアは記録されるが実際の停止判断に使われず、UI 表示以上の意味を持たない
3. **DynamicOrder の LLM 呼び出しコスト** — free_talk では毎発言ごとに軽量 LLM を呼ぶため、ラウンドあたり 8 回追加呼び出し
4. **PrivateInstruction の rigidity** — 「Round 2 で 1 回は反論」など固定ルールが Meeting Phase 4 に埋め込まれており、ODSC に応じた柔軟化が難しい
5. **ConversationMemory の要約タイミング** — 前ラウンド全体を LLM 要約するが、非同期の合流ポイントがラウンド境界のみ
6. **6 パートリーダー固定** — Code Review は概念/観点数がハードコード。ドメイン固有 (ML paper / infra code / frontend etc.) に切り替えられない
7. **発言長制限 (200 chars)** — 短さ優先で、複雑な論点を 1 発言で展開しにくい (代わりに複数往復が必要)
8. **Follow-up の履歴継承範囲** — 親セッションの report.md しか渡さないため、細かい round-level の文脈が失われる
9. **Intervention が事実上ダミー** — v1.0 は `NoIntervention` のみで、UI からの割り込みや指示注入ができない
10. **Code Review Phase 4 の 3 ラウンド固定** — ODSC/focus に関わらず必ず 3 ラウンド (課題報告 → 深掘り → 合意) となっており、findings の量や複雑さに応じたスケーリングがない

---

## 参照ファイル一覧

### コアモジュール
- [misc_26/Orchestra/core/data_models.py](misc_26/Orchestra/core/data_models.py) — データクラス全体
- [misc_26/Orchestra/core/orchestrator.py](misc_26/Orchestra/core/orchestrator.py) — Phase 1 計画立案
- [misc_26/Orchestra/core/conductor.py](misc_26/Orchestra/core/conductor.py) — Phase 2 進行管理
- [misc_26/Orchestra/core/agent.py](misc_26/Orchestra/core/agent.py) — AI エージェント
- [misc_26/Orchestra/core/memory.py](misc_26/Orchestra/core/memory.py) — 会話メモリ・コンテキスト
- [misc_26/Orchestra/core/convergence.py](misc_26/Orchestra/core/convergence.py) — 収束判定・堂々巡り検知
- [misc_26/Orchestra/core/speaking_order.py](misc_26/Orchestra/core/speaking_order.py) — 発言順序戦略
- [misc_26/Orchestra/core/turn_calculator.py](misc_26/Orchestra/core/turn_calculator.py) — 時間推定
- [misc_26/Orchestra/core/time_keeper.py](misc_26/Orchestra/core/time_keeper.py) — 時間管理
- [misc_26/Orchestra/core/intervention.py](misc_26/Orchestra/core/intervention.py) — ユーザー介入インターフェース
- [misc_26/Orchestra/core/synthesizer.py](misc_26/Orchestra/core/synthesizer.py) — Phase 3 評価統合
- [misc_26/Orchestra/core/output_generator.py](misc_26/Orchestra/core/output_generator.py) — 出力ファイル生成

### 機能①: Idea Discussion
- [misc_26/Orchestra/features/idea_discussion.py](misc_26/Orchestra/features/idea_discussion.py) — エントリポイント

### 機能②: Code Review
- [misc_26/Orchestra/features/code_review/code_review.py](misc_26/Orchestra/features/code_review/code_review.py) — エントリポイント
- [misc_26/Orchestra/features/code_review/phases.py](misc_26/Orchestra/features/code_review/phases.py) — Phase 3-5 ラッパー
- [misc_26/Orchestra/features/code_review/meeting.py](misc_26/Orchestra/features/code_review/meeting.py) — Phase 4 全体会議
- [misc_26/Orchestra/features/code_review/investigator.py](misc_26/Orchestra/features/code_review/investigator.py) — Phase 2 個別調査
- [misc_26/Orchestra/features/code_review/cross_question.py](misc_26/Orchestra/features/code_review/cross_question.py) — Phase 3 相互質問

### Web UI
- [misc_26/Orchestra/web/routes/api_idea.py](misc_26/Orchestra/web/routes/api_idea.py) — POST /api/idea/plan / stream
- [misc_26/Orchestra/web/routes/api_review.py](misc_26/Orchestra/web/routes/api_review.py) — POST /api/review/stream
- [misc_26/Orchestra/web/routes/api_sessions.py](misc_26/Orchestra/web/routes/api_sessions.py) — GET /api/sessions* (履歴・復元)
- [misc_26/Orchestra/web/static/js/sse.js](misc_26/Orchestra/web/static/js/sse.js) — SSE クライアント (OrchestraSSE)

### 設定
- [misc_26/Orchestra/config/settings.yaml](misc_26/Orchestra/config/settings.yaml) — グローバル設定
- [misc_26/Orchestra/config/roles/](misc_26/Orchestra/config/roles/) — ロール定義 (theorist, devil, implementer 等)

### 設計ドキュメント
- [misc_26/Orchestra/doc/design/03_architecture.md](misc_26/Orchestra/doc/design/03_architecture.md) — 全体アーキテクチャ
- [misc_26/Orchestra/doc/design/04_orchestrator.md](misc_26/Orchestra/doc/design/04_orchestrator.md) — Phase 1 詳細設計
- [misc_26/Orchestra/doc/design/05_conductor.md](misc_26/Orchestra/doc/design/05_conductor.md) — Phase 2 進行管理
- [misc_26/Orchestra/doc/design/06_agent.md](misc_26/Orchestra/doc/design/06_agent.md) — エージェント設計
- [misc_26/Orchestra/doc/design/08_memory_context.md](misc_26/Orchestra/doc/design/08_memory_context.md) — メモリ・コンテキスト
- [misc_26/Orchestra/doc/design/09_evaluation_feedback.md](misc_26/Orchestra/doc/design/09_evaluation_feedback.md) — Phase 3 評価
- [misc_26/Orchestra/doc/design/10_turn_management.md](misc_26/Orchestra/doc/design/10_turn_management.md) — ターン・時間管理
- [misc_26/Orchestra/doc/design/11_idea_discussion.md](misc_26/Orchestra/doc/design/11_idea_discussion.md) — 機能①詳細
- [misc_26/Orchestra/doc/design/12_code_review.md](misc_26/Orchestra/doc/design/12_code_review.md) — 機能②詳細
- [misc_26/Orchestra/doc/design/14_output_format.md](misc_26/Orchestra/doc/design/14_output_format.md) — 出力フォーマット
- [misc_26/Orchestra/doc/design/17_settings.md](misc_26/Orchestra/doc/design/17_settings.md) — 設定詳細

---

**作成日**: 2026-07-02
**対象版**: v1.0
**検証対象範囲**: misc_26/Orchestra/ 全体
**このドキュメントの用途**: Claude への改善プロンプト作成時の基盤資料
