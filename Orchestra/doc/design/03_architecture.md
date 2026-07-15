# 第3章 全体アーキテクチャ

---

## 3.1 3フェーズ構成

AI Orchestra は全ての処理を**3つのフェーズ**に分離して実行します。各フェーズは異なる目的を持ち、異なるモデルが担当します。この分離により、計画の質・議論の速度・統合の深さを独立して最適化できます。

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   Phase 1      │     │   Phase 2      │     │   Phase 3      │
│   計画立案      │────→│   議論進行      │────→│   統合・評価    │
│   (Planning)   │     │  (Discussion)  │     │  (Synthesis)   │
│                │     │                │     │                │
│  gpt-5.4       │     │  gpt-4.1       │     │ claude-s4-5    │
│  level=high    │     │  level=minimal │     │  extended      │
│  ~4秒          │     │  ~180秒        │     │  thinking      │
│                │     │                │     │  ~25秒         │
└────────────────┘     └────────────────┘     └────────────────┘
   ↓出力                  ↓出力                  ↓出力
 ・ODSC                 ・議論ログ              ・最終レポート
 ・参加AI選定           ・収束スコア推移        ・評価結果
 ・議論計画             ・各AIの発言            ・YAMLフィードバック
 ・個別指示             ・指揮者メモ            ・要約
```

---

### 3.1.1 Phase 1: 計画立案（Planning）

**目的**: ユーザーの入力を分析し、最適な議論の「設計図」を作成する。

**担当モデル**: `gpt-5.4`（reasoning_effort=high）

**選定理由**:
- 1M token の入力コンテキストにより、全ロール YAML + 過去フィードバック + ユーザー入力を一度に処理可能
- reasoning_effort=high で深い計画立案ができる
- 計画は1回だけ生成するため、応答速度（~4秒）は許容範囲

**入力**:

```
┌─────────────────────────────────────────┐
│ ユーザーの入力テーマ / プロンプト          │
│ 利用可能ロール一覧 (YAML 全文)           │
│ 各ロールの過去フィードバック履歴          │
│ 設定値 (時間制限, 最大AI数, 収束閾値)    │
│ follow-up の場合: 前回セッション情報      │
│ シナリオテンプレート (該当する場合)       │
└─────────────────────────────────────────┘
```

**出力**:

```json
{
"odsc": {
"objective": "議論の目的",
"deliverable": "成果物の定義",
"success_criteria": "成功基準",
"convergence_threshold": 0.8
},
"selected_agents": [
{"role_id": "theorist", "model": "gpt-5.4", "level": "high", "reason": "...", "expected_contribution": "..."},
{"role_id": "devil", "model": "claude-sonnet-4-5", "level": "medium", "reason": "...", "expected_contribution": "..."}
],
"discussion_plan": {
"estimated_rounds": 5,
"round_config": [
{"round": 1, "phase_name": "...", "speakers": [...], "pattern": "one_shot", "level": "medium", "time_budget_sec": 40, "goal": "..."}
],
"total_estimated_time_sec": 190,
"total_estimated_requests": 52
},
"private_instructions": {
"theorist": "あなたへの期待は...",
"devil": "あなたへの期待は..."
}
}
```

**処理の流れ**:

```
1. ユーザー入力のテーマ分析
2. 利用可能ロール群から最適な参加者を選定
    - domain_tags とテーマのマッチング
    - 過去フィードバックの参照（成長傾向のあるロールを優先）
    - ロール間バランスの確保（攻め/守り/俯瞰）
3. ODSC の策定
4. ラウンド構成の決定
    - ラウンド数の算出
    - 各ラウンドの目標・参加者・level・時間配分
    - 発言パターンの選択 (one_shot / ping_pong / free_talk)
5. 各AIへの個別指示の生成
    - 期待する貢献の明文化
    - 過去フィードバックの改善点を反映
    - 発言ルールの付与
6. 時間制限内に収まるか検証
    - 収まらない場合は計画を再調整
```

---

### 3.1.2 Phase 2: 議論進行（Discussion）

**目的**: Phase 1 で策定した計画に基づき、AI エージェント間の議論を進行・制御する。

**担当モデル**: `gpt-4.1`（temperature=0.3, 進行管理用）+ 各エージェントのモデル

**選定理由**:
- 進行管理（発言順決定、収束判定）は定型的処理であり、高速・安定・低コストが求められる
- gpt-4.1 は temperature 制御が可能で、確定的な進行判断に適する
- 各エージェントの発言には各ロール YAML で指定されたモデルを使用

**入力（各ラウンド）**:

```
┌─────────────────────────────────────────┐
│ 議論計画 (Phase 1 出力)                   │
│ 現在のラウンド設定                        │
│ これまでの議論ログ（またはその要約）       │
│ 各AIへの個別指示                          │
│ 時間残量                                  │
└─────────────────────────────────────────┘
```

**出力**:

```
┌─────────────────────────────────────────┐
│ 全ラウンドの発言ログ (JSON)               │
│ 各ラウンドの収束スコア推移                │
│ 指揮者の内部メモ (時間調整等)             │
│ 最終収束スコア                            │
└─────────────────────────────────────────┘
```

**処理の流れ（ラウンドごと）**:

```
for each round in discussion_plan.round_config:
    1. 時間チェック: 残り時間で次ラウンドを実行可能か?
        - NO → 強制終了、Phase 3 へ
    2. Conductor がラウンド開始指示を生成 (gpt-4.1, minimal)
    3. 発言順序の決定
        - pattern=fixed: 計画通りの順序
        - pattern=dialectic: 対立するロールを交互に
        - pattern=free_talk: 直前の発言に反応する形で次を決定
    4. 各AIの発言取得 (直列実行)
        a. コンテキスト構築 (system prompt + 議論ログ + 個別指示)
        b. KotoBuddy API 呼び出し
        c. 発言をログに追記
        d. 進捗バー更新
    5. 収束判定 (gpt-4.1, minimal)
        - score >= threshold → ラウンド終了、Phase 3 へ
        - score 停滞3ラウンド連続 → 計画再立案 or 強制終了
        - 堂々巡り検知 → 新論点の強制
    6. 指揮者内部メモ更新
        - 時間超過/余裕の記録
        - 次ラウンドの時間調整
```

**Phase 2 内のリクエスト分布（5ラウンド×3AI の場合）**:

| リクエスト種類 | 回数 | モデル | level |
|---|---|---|---|
| ラウンド開始指示 | 5 | gpt-4.1 | minimal |
| エージェント発言 | 15 (5×3) | 各ロール指定 | 計画指定 |
| 収束判定 | 5 | gpt-4.1 | minimal |
| 堂々巡り検知 | 2 (必要時のみ) | gpt-4.1 | minimal |
| **合計** | **~27** | — | — |

---

### 3.1.3 Phase 3: 統合・要約・評価（Synthesis）

**目的**: 議論ログ全体を分析し、最終レポート・評価結果・フィードバックを生成する。

**担当モデル**: `claude-sonnet-4-5`（拡張思考、budget_tokens=16000）

**選定理由**:
- 拡張思考により、議論全体を深く分析して統合できる
- 思考プロセスが可視化されるため、要約の根拠が追跡可能
- 200K token 入力で標準的な議論ログ（~80K token）を一括処理可能
- 64K token 出力で詳細なレポートを生成可能

**入力**:

```
┌─────────────────────────────────────────┐
│ 議論ログ全文 (Phase 2 出力)              │
│ ODSC (Phase 1 出力)                      │
│ 各AIの個別指示 (期待した貢献)            │
│ 各AIの evaluation_criteria (YAML から)   │
│ 過去フィードバック (YAML から)            │
│ レポートフォーマット指定                   │
└─────────────────────────────────────────┘
```

**出力**:

```
┌─────────────────────────────────────────┐
│ report.md (最終レポート)                   │
│ full_conversation.md (全会話台本)          │
│ evaluation.md (評価詳細)                   │
│ summary.txt (1ページ要約)                  │
│ YAML フィードバック更新データ              │
│ session_meta.json (メタデータ)             │
│ vibe_coding_prompt.md (②のみ)            │
└─────────────────────────────────────────┘
```

**処理の流れ**:

```
1. 各AIに自己評価を依頼 (並列実行可能)
    - 各AI: 自分の evaluation_criteria に沿ってスコア+振り返り
    - 各AI: 他の全参加者をスコア+1行コメントで評価
2. 指揮者が総合評価を生成 (claude-sonnet-4-5, extended thinking)
    - MVP選出
    - ODSC達成度判定
    - 各AIへの個別フィードバック生成
3. 最終レポート生成 (claude-sonnet-4-5, extended thinking)
    - 議論の結論
    - 技術的洞察の抽出
    - 仮説テーブル (機能①)
    - 実験計画 (機能①)
    - 課題一覧+修正方針 (機能②)
4. その他出力ファイルの生成
    - full_conversation.md: ログの整形
    - summary.txt: 1ページ要約
    - vibe_coding_prompt.md: 修正指示書 (②のみ)
5. YAML フィードバック更新
    - 各ロールの feedback_history に追記
    - feedback_stats の再計算
6. session_meta.json の生成
```

**Phase 3 のリクエスト分布（3AI参加の場合）**:

| リクエスト種類 | 回数 | モデル | level |
|---|---|---|---|
| 自己+他者評価 | 3 | 各ロールのモデル | medium |
| 総合評価 | 1 | claude-sonnet-4-5 | high (budget=16000) |
| 最終レポート | 1 | claude-sonnet-4-5 | high (budget=16000) |
| 要約生成 | 1 | gpt-4.1 | medium |
| **合計** | **~6** | — | — |

---

## 3.2 フェーズ別モデル選定戦略

### 設計思想: 「考える」「進める」「まとめる」の分離

```
Phase 1 [考える] → 深く、遅くてもいい → gpt-5.4 (high)
Phase 2 [進める] → 速く、安定的に   → gpt-4.1 (進行) + 各モデル (発言)
Phase 3 [まとめる] → 丁寧に、深く  → claude-sonnet-4-5 (extended thinking)
```

### なぜ Phase ごとにモデルを変えるのか

| 判断軸 | Phase 1 | Phase 2 (進行管理) | Phase 2 (発言) | Phase 3 |
|---|---|---|---|---|
| 必要な思考深度 | 高 | 低 | 中〜高 | 高 |
| 応答速度の重要性 | 低 | **高** | 中 | 低 |
| 呼び出し回数 | 1回 | ~10回 | ~15回 | ~6回 |
| 入力サイズ | 大 (全ロールYAML) | 中 | 中 | 大 (全ログ) |
| 確定性の必要性 | 中 | **高** | 低 | 中 |

### CLI による上書き

ユーザーはフェーズ別に使用モデルを指定できます:

```bash
python main.py idea \
--planner-model gpt-5.4 \
--conductor-model gpt-4.1 \
--synth-model claude-sonnet-4-5 \
"テーマ"
```

### デフォルト値と代替構成

| 構成名 | Phase 1 | Phase 2 (進行) | Phase 3 | 用途 |
|---|---|---|---|---|
| **default** | gpt-5.4 (high) | gpt-4.1 | claude-sonnet-4-5 (thinking) | 標準利用 |
| fast | gpt-5-mini (low) | gpt-4.1-mini | gpt-5 (medium) | 高速版（拡張思考なし） |
| deep | gpt-5.4 (high) | gpt-4.1 | claude-sonnet-4-5 (budget=16000) | 最高品質 |
| budget | gpt-5-mini (minimal) | gpt-4.1-mini | gpt-4.1 | リクエスト節約版 |

---

## 3.3 データフロー図

### 機能①: 技術議論のデータフロー

```
[ユーザー入力]
"点群のGNNで特徴量抽出する設計指針"
│
▼
┌─────────────────────────────────────────────────────────────┐
│ main.py                                                      │
│ ├── 引数パース (click/typer)                                  │
│ ├── 環境変数・.env 読み込み                                   │
│ ├── RateLimitTracker 初期化                                  │
│ └── IdeaDiscussion.run() 呼び出し                            │
└───────────────────────────────┬─────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ features/idea_discussion.py :: IdeaDiscussion.run()          │
│                                                              │
│ ┌──────────── Phase 1 ────────────┐                         │
│ │ orchestrator.plan(                │                         │
│ │   user_input,                    │                         │
│ │   available_roles,               │    → KotoBuddy API      │
│ │   settings                       │      (gpt-5.4, high)    │
│ │ )                                │                         │
│ │ → plan: OrchestraPlan            │                         │
│ └──────────────┬──────────────────┘                         │
│                │                                             │
│                ▼                                             │
│ ┌──── [ユーザー確認] ────┐                                   │
│ │ 計画表示 + 確認プロンプト│                                   │
│ │ "実行しますか？ [Y/n]"  │                                   │
│ └──────────┬─────────────┘                                   │
│            │ (Yes)                                           │
│            ▼                                                 │
│ ┌──────────── Phase 2 ────────────┐                         │
│ │ conductor.run_discussion(         │                         │
│ │   plan,                          │    → KotoBuddy API      │
│ │   agents,                        │      (各モデル)          │
│ │   time_keeper,                   │      × ラウンド数        │
│ │   memory                         │      × 参加AI数         │
│ │ )                                │                         │
│ │ → discussion_log: DiscussionLog  │                         │
│ └──────────────┬──────────────────┘                         │
│                │                                             │
│                ▼                                             │
│ ┌──────────── Phase 3 ────────────┐                         │
│ │ synthesizer.synthesize(           │                         │
│ │   plan,                          │    → KotoBuddy API      │
│ │   discussion_log,                │      (claude-sonnet-4-5 │
│ │   agents                         │       extended thinking)│
│ │ )                                │                         │
│ │ → synthesis: SynthesisResult     │                         │
│ └──────────────┬──────────────────┘                         │
│                │                                             │
│                ▼                                             │
│ ┌──────────── 出力生成 ────────────┐                         │
│ │ output_generator.generate(        │                         │
│ │   plan, discussion_log, synthesis │                         │
│ │ )                                │                         │
│ │ → ファイル群書き出し              │                         │
│ └──────────────┬──────────────────┘                         │
│                │                                             │
└────────────────┼────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ output/20260620_143052_idea/                                  │
│ ├── session_meta.json                                        │
│ ├── discussion.json                                          │
│ ├── full_conversation.md                                     │
│ ├── report.md                                                │
│ ├── evaluation.md                                            │
│ ├── summary.txt                                              │
│ └── (vibe_coding_prompt.md — ②のみ)                         │
└─────────────────────────────────────────────────────────────┘
```

### 機能②: コードレビューのデータフロー

```
[ユーザー入力]
python main.py review --focus pre_submission ./src/
│
▼
┌─────────────────────────────────────────────────────────────┐
│ features/code_review.py :: CodeReview.run()                   │
│                                                              │
│ ┌──── Phase 1: 構造スキャン ────┐                            │
│ │ folder_scanner.scan(path)      │                            │
│ │ → file_tree, headers           │                            │
│ │                                │                            │
│ │ orchestrator.plan_review(      │   → KotoBuddy API         │
│ │   file_tree, headers,          │     (gpt-5.4, minimal)    │
│ │   focus_mode                   │                            │
│ │ )                              │                            │
│ │ → パートリーダー割当           │                            │
│ └──────────────┬────────────────┘                            │
│                ▼                                             │
│ ┌──── Phase 2: 個別調査 ────────┐                            │
│ │ for each part_leader:          │                            │
│ │   leader.investigate(          │   → KotoBuddy API         │
│ │     assigned_files             │     (各モデル, medium)    │
│ │   )                            │                            │
│ │ → 課題リスト (per leader)      │                            │
│ └──────────────┬────────────────┘                            │
│                ▼                                             │
│ ┌──── Phase 3: 相互質問 ────────┐                            │
│ │ cross_question(                │                            │
│ │   leaders, max_rounds=5        │   → KotoBuddy API         │
│ │ )                              │     (各モデル, medium)    │
│ │ → 追加知見・修正された課題      │                            │
│ └──────────────┬────────────────┘                            │
│                ▼                                             │
│ ┌──── Phase 4: 全体会議 ────────┐                            │
│ │ conductor.run_discussion(      │                            │
│ │   review_plan,                 │   → KotoBuddy API         │
│ │   part_leaders                 │     (各モデル, high)      │
│ │ )                              │                            │
│ │ → 優先度付き修正方針           │                            │
│ └──────────────┬────────────────┘                            │
│                ▼                                             │
│ ┌──── Phase 5: レポート生成 ────┐                            │
│ │ synthesizer.synthesize_review( │                            │
│ │   all_findings, discussion     │   → KotoBuddy API         │
│ │ )                              │     (claude-sonnet-4-5,   │
│ │ → report.md                    │      extended thinking)   │
│ │ → vibe_coding_prompt.md        │                            │
│ └──────────────┬────────────────┘                            │
│                │                                             │
└────────────────┼────────────────────────────────────────────┘
│
▼
[output/ にファイル群出力]
```

---

## 3.4 モジュール依存関係

### モジュール一覧と責務

```
core/
├── api_client.py        API呼び出しの抽象化（リトライ・フォールバック・モード切替）
├── rate_tracker.py      日次リクエスト数の追跡
├── orchestrator.py      Phase 1: 計画立案ロジック
├── conductor.py         Phase 2: 議論進行管理
├── synthesizer.py       Phase 3: 統合・要約・レポート生成
├── agent.py             AIエージェントの基底クラス（ロールYAML読込+API呼出）
├── memory.py            会話ログのJSON管理・コンテキスト構築
├── evaluator.py         自己/他者評価ロジック
├── feedback.py          YAMLフィードバック蓄積・読出
├── follow_up.py         継続議論のコンテキスト管理
├── time_keeper.py       時間管理（残り時間追跡・ラウンド判定）
├── turn_calculator.py   ターン数・時間配分の算出補助
└── intervention.py      将来の介入機能用インターフェース

features/
├── idea_discussion.py   機能①の統合フロー
└── code_review.py       機能②の統合フロー（スキャン+パートリーダー+全体会議）

config/
├── settings.yaml        全体設定
├── roles/               ロール定義YAML群
└── scenarios/           シナリオテンプレート
```

### 依存関係図

```
main.py
├── features/idea_discussion.py
│   ├── core/orchestrator.py
│   │   ├── core/api_client.py
│   │   ├── core/feedback.py
│   │   │   └── config/roles/*.yaml
│   │   └── core/turn_calculator.py
│   ├── core/conductor.py
│   │   ├── core/api_client.py
│   │   ├── core/agent.py
│   │   │   ├── core/api_client.py
│   │   │   ├── core/memory.py
│   │   │   └── config/roles/*.yaml
│   │   ├── core/time_keeper.py
│   │   ├── core/memory.py
│   │   └── core/intervention.py
│   ├── core/synthesizer.py
│   │   ├── core/api_client.py
│   │   ├── core/evaluator.py
│   │   │   └── core/api_client.py
│   │   └── core/feedback.py
│   ├── core/follow_up.py (--follow-up時のみ)
│   └── core/rate_tracker.py
│
├── features/code_review.py
│   ├── (上記と同じcore/モジュール群を使用)
│   ├── folder_scanner (code_review.py内部)
│   ├── part_leader (code_review.py内部)
│   └── vibe_prompt_generator (code_review.py内部)
│
└── config/settings.yaml
```

### モジュール間のインターフェース（主要なデータ型）

```python
# --- Phase 1 の出力 ---
@dataclass
class OrchestraPlan:
odsc: ODSC
selected_agents: list[AgentConfig]
discussion_plan: DiscussionPlan
private_instructions: dict[str, str]

@dataclass
class ODSC:
objective: str
deliverable: str
success_criteria: str
convergence_threshold: float

@dataclass
class AgentConfig:
role_id: str
model: str
level: str
reason: str
expected_contribution: str

@dataclass
class DiscussionPlan:
estimated_rounds: int
round_config: list[RoundConfig]
total_estimated_time_sec: float
total_estimated_requests: int

@dataclass
class RoundConfig:
round: int
phase_name: str
speakers: list[str]
pattern: str  # "one_shot" | "ping_pong" | "free_talk"
level: str
time_budget_sec: float
goal: str

# --- Phase 2 の出力 ---
@dataclass
class DiscussionLog:
rounds: list[RoundLog]
total_requests: int
total_tokens: TokenCount
final_convergence_score: float

@dataclass
class RoundLog:
round: int
phase_name: str
goal: str
started_at: str
ended_at: str
duration_sec: float
private_instructions: dict[str, InstructionLog]
public_utterances: list[Utterance]
convergence_check: ConvergenceResult
orchestrator_memo: str

@dataclass
class Utterance:
sequence: int
speaker: str
speaker_display: str
type: str  # "instruction" | "discussion"
content: str
model: str
level: str
tokens_used: TokenCount
duration_sec: float

@dataclass
class ConvergenceResult:
score: float
reasoning: str
remaining_disagreements: list[str]
recommendation: str  # "continue" | "conclude" | "pivot"

# --- Phase 3 の出力 ---
@dataclass
class SynthesisResult:
report_md: str
full_conversation_md: str
evaluation_md: str
summary_txt: str
vibe_coding_prompt_md: str | None
evaluation_data: EvaluationData
feedback_updates: dict[str, FeedbackEntry]
session_meta: dict
```

---

## 3.5 実行シーケンス図

### 標準的な機能①実行のシーケンス

```
時間軸 →
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[User]   [main.py]  [Orchestrator] [Conductor]  [Agent×3]  [Synthesizer] [API]
  │          │            │            │            │            │          │
  │─ idea ──→│            │            │            │            │          │
  │          │            │            │            │            │          │
  │          │──plan()───→│            │            │            │          │
  │          │            │──────────────────────────────────────────── req→│
  │          │            │←──────────────────────────────────────── res ──│
  │          │←──plan ────│            │            │            │          │
  │          │            │            │            │            │          │
  │←─ 計画表示+確認 ──────│            │            │            │          │
  │── "Y" ──→│            │            │            │            │          │
  │          │            │            │            │            │          │
  │          │── run_discussion() ───→│            │            │          │
  │          │            │            │            │            │          │
  │          │            │  ┌── Round 1 ─────────────────────┐ │          │
  │          │            │  │         │            │          │ │          │
  │          │            │  │─ 開始指示 ────────────────── req→│          │
  │          │            │  │←─────────────────────────── res──│          │
  │          │            │  │         │            │          │ │          │
  │          │            │  │── ctx ──→│ Agent A    │          │ │          │
  │          │            │  │         │──────────────────── req→│          │
  │          │            │  │         │←────────────────── res──│          │
  │←── 発言表示 ──────────│  │←─ utterance ─│            │          │          │
  │          │            │  │         │            │          │ │          │
  │          │            │  │── ctx ──→│ Agent B    │          │ │          │
  │          │            │  │         │──────────────────── req→│          │
  │          │            │  │         │←────────────────── res──│          │
  │←── 発言表示 ──────────│  │←─ utterance ─│            │          │          │
  │          │            │  │         │            │          │ │          │
  │          │            │  │── ctx ──→│ Agent C    │          │ │          │
  │          │            │  │         │──────────────────── req→│          │
  │          │            │  │         │←────────────────── res──│          │
  │←── 発言表示 ──────────│  │←─ utterance ─│            │          │          │
  │          │            │  │         │            │          │ │          │
  │          │            │  │─ 収束判定 ────────────────── req→│          │
  │          │            │  │←─ score=0.40 ───────────── res──│          │
  │          │            │  │         │            │          │ │          │
  │          │            │  └── continue ────────────────────┘ │          │
  │          │            │            │            │            │          │
  │          │            │  ┌── Round 2〜4 (同様) ────────────┐│          │
  │          │            │  │         ...                     ││          │
  │          │            │  └── score ≥ 0.80 → conclude ─────┘│          │
  │          │            │            │            │            │          │
  │          │←── discussion_log ─────│            │            │          │
  │          │            │            │            │            │          │
  │          │── synthesize() ──────────────────────────────────→│          │
  │          │            │            │            │            │          │
  │          │            │            │  ┌── 評価依頼 (並列) ─┐│          │
  │          │            │            │  │ Agent A ──── req→│  ││          │
  │          │            │            │  │ Agent B ──── req→│  ││          │
  │          │            │            │  │ Agent C ──── req→│  ││          │
  │          │            │            │  │←──────── res×3 ──┘  ││          │
  │          │            │            │  └────────────────────┘│          │
  │          │            │            │            │            │          │
  │          │            │            │            │── 統合 ─── req→│     │
  │          │            │            │            │←──────── res──│     │
  │          │            │            │            │── レポ ── req→│     │
  │          │            │            │            │←──────── res──│     │
  │          │            │            │            │            │          │
  │          │←── synthesis_result ──────────────────────────────│          │
  │          │            │            │            │            │          │
  │          │── write files ──→ [output/]          │            │          │
  │          │── update YAML ──→ [config/roles/]    │            │          │
  │          │            │            │            │            │          │
  │←── 完了表示 ──────────│            │            │            │          │
  │          │            │            │            │            │          │
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     0s      1s          5s                     190s         215s     216s
```

### 時間配分の典型例（5分制限）

```
|←───── 300秒 (5分) ─────────────────────────────────────────→|
|                                                              |
|Phase1|                Phase 2                  |  Phase 3   |
| 4秒  |              ~180秒                     |   ~25秒    |
|      |                                         |            |
|計画  |R1(40s)|R2(40s)|R3(80s)|R4(30s)|        |統合+評価   |
|      |       |       |       |       |        |            |
|      |← 進行管理オーバーヘッド: 各3秒×4 = 12秒→|            |
```

### エラー発生時のシーケンス

```
[Conductor]          [Agent A]          [API]
     │                   │                │
     │── ctx ──────────→│                │
     │                   │─── request ──→│
     │                   │←── 404 ───────│  (モデルEOL)
     │                   │                │
     │                   │  [リトライ: フォールバックモデルで再試行]
     │                   │                │
     │                   │─── request ──→│  (fallback model)
     │                   │←── 200 ───────│
     │←── utterance ─────│                │
     │                   │                │
     │  [指揮者メモ: "Agent Aのモデルをフォールバック。次回YAML更新推奨"]
     │                   │                │
```

### Phase 2 の評価フェーズ（並列実行）

```
[Synthesizer]   [Agent A]   [Agent B]   [Agent C]   [API]
     │              │           │           │         │
     │── 評価依頼 ─→│           │           │         │
     │── 評価依頼 ──────────────→│           │         │
     │── 評価依頼 ──────────────────────────→│         │
     │              │           │           │         │
     │              │─── req ───────────────────────→│ (並列)
     │              │           │─── req ───────────→│ (並列)
     │              │           │           │─ req ─→│ (並列)
     │              │           │           │         │
     │              │←── res ───────────────────────│
     │              │           │←── res ───────────│
     │              │           │           │← res ─│
     │              │           │           │         │
     │←── eval ────│           │           │         │
     │←── eval ────────────────│           │         │
     │←── eval ────────────────────────────│         │
     │              │           │           │         │
     │  [全評価を統合して総合評価を生成]      │         │
     │─── 統合リクエスト ──────────────────────────────→│
     │←── 総合評価 ────────────────────────────────────│
```

---

### 3章まとめ: アーキテクチャの設計原則

| 原則 | 具体的実現 |
|---|---|
| **関心の分離** | 計画 / 進行 / 統合を独立フェーズに分離。各フェーズは独自のモデル・パラメータで最適化 |
| **適材適所** | 深い思考には gpt-5.4/claude、高速進行には gpt-4.1、拡張思考による統合には claude-sonnet-4-5 |
| **耐障害性** | 各 API 呼出にリトライ+フォールバック。1エージェントの失敗が全体を止めない |
| **観測可能性** | 全フェーズの入出力を JSON ログに記録。指揮者の内部判断も含めて追跡可能 |
| **拡張性** | InterventionHandler による介入ポイント確保。新ロール追加は YAML 配置のみ |
| **時間制約遵守** | TimeKeeper が全フェーズを通じて時間を追跡。超過前に計画を動的調整 |

---
