# AI Orchestra — タスク分割・実装順序

> 依存関係に基づいた実装タスクの全容と優先順位

---

## 1. 全体マップ

```
Phase A: 基盤             ██░░░░░░░░░░░░░░░░░░  (4タスク)
Phase B: API + 時間管理    ████░░░░░░░░░░░░░░░░  (4タスク)
Phase C: エージェント基盤  ██████░░░░░░░░░░░░░░  (4タスク)
Phase D: 3フェーズエンジン ████████░░░░░░░░░░░░  (4タスク)
Phase E: 統合 + 出力      ██████████░░░░░░░░░░  (4タスク)
Phase F: 追加機能         ████████████░░░░░░░░  (3タスク)
Phase G: CLI + 表示       ██████████████░░░░░░  (5タスク)
Phase H: Web UI 基盤      ████████████████░░░░  (4タスク)
Phase I: Web UI 機能      ██████████████████░░  (4タスク)
Phase J: Web UI 仕上げ    ████████████████████  (3タスク)
                                                 計: 39タスク
```

---

## 2. 依存関係グラフ

```
A-1 exceptions
│
├── A-3 config_loader ← A-2 settings.yaml
│   │
│   ├── B-1 rate_tracker
│   │   │
│   │   └── B-2 api_client
│   │       │
│   │       ├── C-3 memory
│   │       │   │
│   │       │   └── C-4 agent ← C-1 role_manager ← C-2 roles/*.yaml
│   │       │       │
│   │       │       ├── D-1 orchestrator
│   │       │       │   │
│   │       │       │   └── D-2 conductor ← B-3 time_keeper, B-4 turn_calculator
│   │       │       │       │
│   │       │       │       └── D-3 evaluator
│   │       │       │           │
│   │       │       │           └── D-4 synthesizer
│   │       │       │               │
│   │       │       │               ├── E-1 feedback
│   │       │       │               ├── E-2 output_generator
│   │       │       │               └── E-4 idea_discussion ← E-3 intervention
│   │       │       │                   │
│   │       │       │                   ├── F-1 follow_up
│   │       │       │                   ├── F-2 code_review
│   │       │       │                   └── F-3 scenarios/*.yaml
│   │       │       │
│   │       │       └── G-1〜G-4 display/*.py
│   │       │           │
│   │       │           └── G-5 main.py
│   │       │
│   │       └── H-1〜H-4 Web UI 基盤
│   │           │
│   │           ├── I-1〜I-4 Web UI 機能
│   │           │   │
│   │           │   └── J-1〜J-3 Web UI 仕上げ
│
A-4 mock_api (テスト用、依存なし)
```

---

## 3. Phase A: 基盤

### A-1. core/exceptions.py

| 項目 | 内容 |
|------|------|
| **参照** | なし（独自定義） |
| **依存** | なし |
| **テスト** | 不要（定義のみ） |
| **推定時間** | 15分 |
| **行数目安** | 80行 |

```
実装内容:
- OrchestraError (基底例外)
- OrchestraAPIError(OrchestraError)
- ModelNotFoundError(OrchestraAPIError) — model: str 属性
- AuthenticationError(OrchestraAPIError) — is_rate_limit: bool 属性
- RateLimitExhaustedError(OrchestraAPIError)
- EmptyResponseError(OrchestraAPIError)
- MaxRetriesExceededError(OrchestraAPIError)
- TimeoutError(OrchestraAPIError)
- ServerError(OrchestraAPIError) — status_code: int, retryable: bool
- RoleNotFoundError(OrchestraError)
- RoleValidationError(OrchestraError)
- SessionNotFoundError(OrchestraError)
- InputTooShortError(OrchestraError)
- InputTooLongError(OrchestraError)
- ChainTooDeepError(OrchestraError)
- ConfigLoadError(OrchestraError)
```

---

### A-2. config/settings.yaml

| 項目 | 内容 |
|------|------|
| **参照** | `doc/17_settings.md` |
| **依存** | なし |
| **テスト** | 不要 |
| **推定時間** | 10分 |

```
実装内容:
- 17章の完全版 settings.yaml をそのままコピー
```

---

### A-3. core/config_loader.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/17_settings.md`, `doc/02_api_specification.md` §2.7 |
| **依存** | A-2 |
| **テスト** | tests/unit/test_config_loader.py |
| **推定時間** | 45分 |
| **行数目安** | 150行 |

```
実装内容:
- Settings dataclass
- Settings.load(config_dir: Path) クラスメソッド
- .env パーサー
- 環境変数読み込み (KOTOBUDDY_*, AZURE_OPENAI_* フォールバック)
- 優先順位: CLI引数 > .env > 環境変数 > settings.yaml
- get_timeout(model: str) → int
- get_level_time(level: str, model: str) → float
- get_expertise_config(level: str) → dict
```

---

### A-4. tests/mocks/mock_api.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/18_roadmap.md` §18.5 |
| **依存** | なし |
| **テスト** | 不要（テスト用ユーティリティ） |
| **推定時間** | 20分 |
| **行数目安** | 60行 |

```
実装内容:
- MockAPIClient クラス
- __init__(responses: list[dict] | None)
- async call(model, messages, **kwargs) → dict
- call_log: list[dict]
- call_count: int (property)
- mode: str = "openai"
- assert_called_with_model(model)
- assert_call_count(expected)
- assert_no_temperature()
- assert_no_max_tokens()
```

---

## 4. Phase B: API + 時間管理

### B-1. core/rate_tracker.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/15_error_handling.md` §15.4 |
| **依存** | A-1 |
| **テスト** | tests/unit/test_rate_tracker.py |
| **推定時間** | 30分 |
| **行数目安** | 100行 |

```
実装内容:
- RateLimitTracker dataclass
- daily_limit, safety_margin, request_count, last_reset
- persistence_path: Path
- increment(n: int = 1)
- remaining() → int
- can_proceed(estimated_requests: int) → bool
- utilization() → float
- _check_reset() → 日付変わりでリセット
- _save() / _load() → JSON永続化
```

---

### B-2. core/api_client.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/02_api_specification.md`, `doc/15_error_handling.md` §15.1-15.3 |
| **依存** | A-1, A-3, B-1 |
| **テスト** | tests/unit/test_api_client.py |
| **推定時間** | 90分 |
| **行数目安** | 280行 |

```
実装内容:
- detect_mode(endpoint, explicit_mode) → str
- RetryConfig dataclass
- RetryHandler クラス
- FallbackManager クラス
- EmptyResponseHandler クラス
- ResilientAPIClient クラス
  - async call(model, messages, **kwargs) → dict
  - async call_raw(model, messages, **kwargs) → dict
  - _build_params(model, messages, **kwargs) → dict
  - _build_params_gpt5 / _build_params_claude_thinking / _build_params_standard
  - _is_gpt5_series(model) → bool
  - _is_claude_thinking(model) → bool
  - _classify_error(exception, model) → 例外型
```

---

### B-3. core/time_keeper.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/10_turn_management.md` §10.2 |
| **依存** | A-1 |
| **テスト** | tests/unit/test_time_keeper.py |
| **推定時間** | 30分 |
| **行数目安** | 80行 |

```
実装内容:
- TimePressure Enum
- TimeKeeper dataclass
  - elapsed, discussion_budget, discussion_elapsed, remaining (properties)
  - pressure → TimePressure (property)
  - can_start_next_round(estimated_round_sec) → bool
  - record_round(duration_sec)
  - get_moving_average(window=3) → float
  - force_conclude() → bool
```

---

### B-4. core/turn_calculator.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/10_turn_management.md` §10.1, §10.3 |
| **依存** | A-3 |
| **テスト** | tests/unit/test_turn_calculator.py |
| **推定時間** | 30分 |
| **行数目安** | 100行 |

```
実装内容:
- LEVEL_TIME_MAP 定数
- CONDUCTOR_OVERHEAD_PER_ROUND 定数
- TurnCalculator クラス
  - calculate_round_time(round_config) → float
  - calculate_total_time(plan) → float
  - fits_in_budget(plan, time_limit) → bool
  - estimate_utterance_time(model, level) → float
- DynamicPlanAdjuster クラス
  - adjust_for_time_overrun(plan, completed_rounds, time_keeper) → list[RoundConfig]
  - _downgrade_level(level) → str
```

---

## 5. Phase C: エージェント基盤

### C-1. core/role_manager.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/07_role_definitions.md` §7.1, §7.4 |
| **依存** | A-1, A-3 |
| **テスト** | tests/unit/test_role_manager.py |
| **推定時間** | 25分 |
| **行数目安** | 70行 |

```
実装内容:
- RoleManager クラス
  - __init__(roles_dir: Path)
  - load_role(role_id: str) → dict
  - list_available_roles() → list[dict]
  - _validate_role(role: dict)
  - REQUIRED_FIELDS 定数
```

---

### C-2. config/roles/*.yaml (8ファイル)

| 項目 | 内容 |
|------|------|
| **参照** | `doc/99_appendix.md` 付録A |
| **依存** | なし |
| **テスト** | 不要 |
| **推定時間** | 20分 |

```
作成ファイル:
- theorist.yaml
- experimentalist.yaml
- implementer.yaml
- literature.yaml
- devil.yaml
- bird_eye.yaml
- code_architect.yaml
- code_reviewer.yaml
```

---

### C-3. core/memory.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/08_memory_context.md` |
| **依存** | A-1, B-2 |
| **テスト** | tests/unit/test_memory.py |
| **推定時間** | 60分 |
| **行数目安** | 200行 |

```
実装内容:
- ConversationMemory クラス
  - add_utterance(utterance, round_num)
  - add_system_event(event, round_num)
  - get_round_utterances(round_num) → list[dict]
  - get_last_utterance(round_num) → dict | None
  - get_context_for_agent(current_round, agent_role_id, context_budget) → dict
  - get_full_log_text() → str
  - get_context_summary() → str
  - async summarize_round(round_log)
  - export_json() → dict
- ContextBudget クラス
  - MODEL_LIMITS 定数
  - estimate_tokens(text) → int
  - fits(system_prompt, user_message) → bool
  - trim_to_fit(system_prompt, user_message) → str
```

---

### C-4. core/agent.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/06_agent.md` |
| **依存** | A-1, B-2, C-1, C-3 |
| **テスト** | tests/unit/test_agent.py |
| **推定時間** | 60分 |
| **行数目安** | 250行 |

```
実装内容:
- Agent クラス
  - async speak(round_context, additional_instruction="") → Utterance
  - async evaluate(discussion_log, all_agents) → dict
  - set_private_instruction(instruction)
  - set_feedback_context(context)
  - set_speaking_rules(rules)
  - _build_system_prompt() → str
  - _build_context_message(round_context, additional_instruction) → str
  - _build_api_params(system_prompt, user_message) → dict
  - _build_api_params_gpt5 / _claude_thinking / _standard
  - _is_too_long(content) → bool
  - async _request_shorter(original_content, round_context) → str
  - MAX_UTTERANCE_CHARS, CLAUDE_THINKING_BUDGET 定数
```

---

## 6. Phase D: 3フェーズエンジン

### D-1. core/orchestrator.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/04_orchestrator.md` |
| **依存** | A-1, B-2, B-4, C-1, E-1 (interface only) |
| **テスト** | tests/unit/test_orchestrator.py |
| **推定時間** | 90分 |
| **行数目安** | 250行 |

```
実装内容:
- Orchestrator クラス
  - async plan(user_input, model, level, time_limit_sec, max_agents, expertise, follow_up_context, scenario) → OrchestraPlan
  - _build_planning_prompt(user_input, roles, settings, follow_up, scenario) → str
  - _parse_plan_response(response_content) → OrchestraPlan
  - _validate_plan(plan, time_limit) → OrchestraPlan
  - PLANNING_PROMPT テンプレート
```

---

### D-2. core/conductor.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/05_conductor.md`, `doc/10_turn_management.md` §10.4 |
| **依存** | A-1, B-2, B-3, C-3, C-4, D-1(型), E-3 |
| **テスト** | tests/unit/test_conductor.py |
| **推定時間** | 120分 |
| **行数目安** | 300行 (上限) |

```
実装内容:
- ConvergenceChecker クラス
- RepetitionDetector クラス
- AgreementDetector クラス
- Conductor クラス
  - async run_discussion(plan) → DiscussionLog
  - async run_round(round_config, plan) → RoundLog
  - async _run_one_shot / _run_ping_pong / _run_free_talk
  - async _decide_next_speaker(speakers, context, counts) → str
  - async _handle_time_pressure / _handle_early_convergence / _handle_stagnation
  - async _force_new_topic / _handle_excessive_agreement
  - _estimate_round_time(round_config) → float
```

---

### D-3. core/evaluator.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/09_evaluation_feedback.md` §9.1, §9.2 |
| **依存** | A-1, B-2, C-4 |
| **テスト** | tests/unit/test_evaluator.py |
| **推定時間** | 45分 |
| **行数目安** | 150行 |

```
実装内容:
- Evaluator クラス
  - async request_self_evaluation(agent, discussion_log, plan) → dict
  - async request_peer_evaluation(agent, other_agents, discussion_log) → dict
  - async request_combined_evaluation(agent, other_agents, discussion_log, plan) → dict
  - _build_self_eval_prompt / _build_peer_eval_prompt
  - _parse_evaluation_response(content) → dict
  - SELF_EVALUATION_PROMPT / PEER_EVALUATION_PROMPT テンプレート
```

---

### D-4. core/synthesizer.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/09_evaluation_feedback.md` §9.3, `doc/14_output_format.md` |
| **依存** | A-1, B-2, D-3, E-1 |
| **テスト** | tests/unit/test_synthesizer.py |
| **推定時間** | 90分 |
| **行数目安** | 280行 |

```
実装内容:
- Synthesizer クラス
  - async synthesize(plan, discussion_log, memory, agents, model, expertise, follow_up_context) → SynthesisResult
  - async _run_evaluations(agents, discussion_log, plan) → dict
  - async _generate_orchestrator_evaluation(evaluations, plan, log) → dict
  - async _generate_report / _generate_full_conversation / _generate_evaluation_md / _generate_summary
  - async _generate_vibe_prompt(findings, scan_result) → str
  - async _extract_hypotheses(log) → list[dict]
  - _generate_session_meta(plan, log, evaluations) → dict
```

---

## 7. Phase E: 統合 + 出力

### E-1. core/feedback.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/09_evaluation_feedback.md` §9.4, §9.5 |
| **依存** | A-1, C-1 |
| **テスト** | tests/unit/test_feedback.py |
| **推定時間** | 45分 |
| **行数目安** | 130行 |

```
実装内容:
- FeedbackManager クラス
  - generate_feedback_context(role_id) → str
  - update_role_feedback(role_id, session_id, date, topic, self_eval, peer_avg, orchestrator_feedback)
  - should_reinforce_rules(role_id) → bool
  - _calculate_stats(history) → dict
  - _calculate_trend(scores) → str
  - _compress_old_entries(history) → list[dict]
  - _most_common_theme(items) → str
```

---

### E-2. core/output_generator.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/14_output_format.md` |
| **依存** | A-1 |
| **テスト** | tests/unit/test_output_generator.py |
| **推定時間** | 30分 |
| **行数目安** | 100行 |

```
実装内容:
- OutputGenerator クラス
  - generate(session_id, plan, discussion_log, synthesis, memory) → Path
  - _write_session_meta / _write_discussion_json / _write_full_conversation
  - _write_report / _write_evaluation / _write_summary / _write_vibe_prompt
  - _generate_session_id(type: str) → str
```

---

### E-3. core/intervention.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/05_conductor.md` §5.7 |
| **依存** | なし |
| **テスト** | 不要（ABC + NoIntervention のみ） |
| **推定時間** | 10分 |
| **行数目安** | 30行 |

```
実装内容:
- InterventionHandler (ABC)
  - check_intervention(round_num, context) → str | None
  - notify_progress(event, data) → None
- NoIntervention(InterventionHandler)
```

---

### E-4. features/idea_discussion.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/11_idea_discussion.md` |
| **依存** | core/ 全体 |
| **テスト** | tests/integration/test_idea_discussion.py |
| **推定時間** | 60分 |
| **行数目安** | 200行 |

```
実装内容:
- IdeaDiscussion クラス
  - async run(user_input, planner_model, conductor_model, synth_model, time_limit, max_agents, expertise, follow_up_id, attached_files, focus_hypotheses, output_dir) → Path
  - _validate_input(user_input) → str
  - _load_follow_up(session_id, attached_files, focus_hypotheses) → FollowUpContext | None
  - _detect_scenario(user_input) → dict | None
  - _confirm_execution(plan) → bool
  - _initialize_agents(plan) → dict[str, Agent]
  - _write_output(plan, log, synthesis, memory, output_dir) → Path
```

---

## 8. Phase F: 追加機能

### F-1. core/follow_up.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/13_follow_up.md` |
| **依存** | A-1, B-2 |
| **テスト** | tests/unit/test_follow_up.py |
| **推定時間** | 60分 |
| **行数目安** | 200行 |

```
実装内容:
- FollowUpContext dataclass
- FollowUpManager クラス
  - load_previous_session(session_id) → FollowUpContext
  - _extract_conclusion / _extract_hypotheses / _extract_unresolved
  - async _compress_discussion(session_dir) → str
- HypothesisManager クラス
  - VALID_TRANSITIONS, apply_updates, generate_table_markdown
- AttachmentProcessor クラス
  - MAX_FILES, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
  - process(file_paths) → list[dict]
```

---

### F-2. features/code_review/

| 項目 | 内容 |
|------|------|
| **参照** | `doc/12_code_review.md` |
| **依存** | core/ 全体 |
| **テスト** | tests/integration/test_code_review.py |
| **推定時間** | 120分 |
| **行数目安** | 複数ファイル計 500行 |

```
実装内容 (5ファイル):
- runner.py: CodeReview クラス (メインフロー)
- scanner.py: FolderScanner クラス
- chunker.py: FileChunker クラス
- part_leader.py: PartLeaderAssigner クラス
- cross_question.py: CrossQuestioner クラス
```

---

### F-3. config/scenarios/*.yaml

| 項目 | 内容 |
|------|------|
| **参照** | `doc/99_appendix.md` 付録I |
| **依存** | なし |
| **テスト** | 不要 |
| **推定時間** | 15分 |

```
作成ファイル:
- algorithm_design.yaml
- experiment_planning.yaml
- paper_discussion.yaml
```

---

## 9. Phase G: CLI + 表示

### G-1〜G-4. display/*.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/16_cli_interface.md` §16.4, §16.5 |
| **依存** | rich, core/ 型定義 |
| **テスト** | 不要（表示のみ） |
| **推定時間** | 各30分 (計120分) |

```
G-1. display/plan_display.py
- PlanDisplay.show(plan, rate_tracker)
- PlanDisplay.confirm_execution() → bool

G-2. display/discussion_display.py
- DiscussionDisplay.show_round_start / show_utterance / show_convergence

G-3. display/progress_display.py
- TimeDisplay.start() / update() / stop()

G-4. display/completion_display.py
- CompletionDisplay.show_completion / show_error
```

---

### G-5. main.py

| 項目 | 内容 |
|------|------|
| **参照** | `doc/16_cli_interface.md` §16.1, §16.2 |
| **依存** | features/, display/, config_loader |
| **テスト** | tests/unit/test_main.py (コマンドパース) |
| **推定時間** | 45分 |
| **行数目安** | 200行 |

```
実装内容:
- typer app 定義
- idea / review / list-roles / history / replay / role-stats コマンド
- _async_run_idea() / _async_run_review() 非同期ラッパー
```

---

## 10. Phase H: Web UI 基盤

### H-1. Web プロジェクト構造 + ベースレイアウト

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-spec.md` Part 2-3, `docs/web-ui-prompts.md` Prompt 1-1 |
| **依存** | なし |
| **推定時間** | 90分 |

```
実装内容:
- web/app.py (FastAPI アプリ)
- web/deps.py (依存注入)
- web/routes/pages.py (HTMLルーティング)
- web/templates/base.html
- web/templates/partials/ (header, toast, modal, step_indicator)
- web/static/css/custom.css
- web/static/js/app.js, dark-mode.js, toast.js
- serve.py (uvicorn起動)
```

---

### H-2. Hero ランディングページ

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 1-2 |
| **依存** | H-1 |
| **推定時間** | 60分 |

```
実装内容:
- web/templates/pages/home.html
- web/routes/api_sessions.py (recent endpoint)
```

---

### H-3. SSE クライアントヘルパー

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 1-3 |
| **依存** | H-1 |
| **推定時間** | 45分 |

```
実装内容:
- web/static/js/sse.js (OrchestraSSE クラス)
```

---

### H-4. SSE バックエンドエンドポイント

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 2-4 |
| **依存** | H-1, E-3 (InterventionHandler), E-4 |
| **推定時間** | 90分 |

```
実装内容:
- web/routes/api_idea.py (plan + stream endpoints)
- SSEInterventionHandler クラス
- _event_generator() 非同期ジェネレータ
```

---

## 11. Phase I: Web UI 機能

### I-1. Idea 議論ページ — 入力 + 計画確認

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 2-1 |
| **依存** | H-1, H-4 |
| **推定時間** | 90分 |

```
実装内容:
- web/templates/pages/idea.html (Step 1 + Step 2)
- Alpine.js 状態管理 (ideaPage関数)
```

---

### I-2. Idea 議論ページ — リアルタイム議論表示

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 2-2 |
| **依存** | I-1, H-3 |
| **推定時間** | 90分 |

```
実装内容:
- web/templates/pages/idea.html (Step 3)
- web/templates/components/chat_bubble.html
- web/templates/components/timer.html
```

---

### I-3. Idea 議論ページ — 結果表示

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 2-3 |
| **依存** | I-2 |
| **推定時間** | 60分 |

```
実装内容:
- web/templates/pages/idea.html (Step 4)
- web/templates/components/evaluation.html
```

---

### I-4. 履歴 + Replay ページ

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 3-1 |
| **依存** | H-1, H-4 |
| **推定時間** | 60分 |

```
実装内容:
- web/templates/pages/history.html
- web/templates/pages/replay.html
- web/routes/api_sessions.py (list, detail, delete, download)
```

---

## 12. Phase J: Web UI 仕上げ

### J-1. ロール管理ページ

| 項目 | 内容 |
|------|------|
| **参照** | `docs/web-ui-prompts.md` Prompt 3-2 |
| **依存** | H-1 |
| **推定時間** | 45分 |

```
実装内容:
- web/templates/pages/roles.html
- web/routes/api_roles.py
```

---

### J-2. Code Review ページ

| 項目 | 内容 |
|------|------|
| **依存** | F-2, H-4 |
| **推定時間** | 90分 |

```
実装内容:
- web/templates/pages/review.html
- web/routes/api_review.py
```

---

### J-3. ダッシュボード + Polish

| 項目 | 内容 |
|------|------|
| **依存** | I-1〜I-4, J-1, J-2 |
| **推定時間** | 60分 |

```
実装内容:
- レスポンシブ調整
- アニメーション微調整
- エラーページ (404, 500)
- ローディング状態の統一
- アクセシビリティ (ARIA)
```

---

## 13. 工数まとめ

| Phase | タスク数 | 推定合計時間 | 主な成果物 |
|-------|---------|------------|-----------|
| A 基盤 | 4 | 1.5時間 | 例外, 設定, モック |
| B API+時間 | 4 | 3時間 | APIクライアント, タイマー |
| C エージェント | 4 | 2.75時間 | ロール, メモリ, Agent |
| D 3フェーズ | 4 | 5.75時間 | Orchestrator, Conductor, Synthesizer |
| E 統合+出力 | 4 | 2.5時間 | フィードバック, 出力, IdeaDiscussion |
| F 追加機能 | 3 | 3.25時間 | フォローアップ, CodeReview |
| G CLI | 5 | 3.5時間 | 表示, main.py |
| H Web基盤 | 4 | 4.75時間 | テンプレート, SSE |
| I Web機能 | 4 | 5時間 | Ideaページ, 履歴 |
| J Web仕上げ | 3 | 3.25時間 | Review, Polish |
| **合計** | **39** | **約35時間** | |

---

## 14. マイルストーン

| マイルストーン | 完了タスク | 確認方法 |
|--------------|-----------|---------|
| **M1: 最小動作** | A全て + B全て + C全て | `pytest tests/unit/` パス |
| **M2: 議論実行可能** | D全て + E全て | `python main.py idea "test"` 成功 |
| **M3: 全CLI機能** | F全て + G全て | 全コマンドが動作 |
| **M4: Web UI MVP** | H全て + I-1〜I-3 | ブラウザで議論実行可能 |
| **M5: 全機能完成** | J全て | 全ページが動作 |

---

## 15. 各タスクの完了基準 (共通)

```
□ 型ヒントが全 public メソッドに付いている
□ Google Style docstring が全 public メソッドに書かれている
□ 対応するユニットテストが存在しパスする
□ 既存テストが全てパスする (pytest tests/unit/)
□ 循環 import がない
□ 1ファイル300行以下
□ 1関数50行以下
□ マジックナンバーが存在しない
□ print() が使われていない
□ Plan (実装計画) → 確認 → 実装 の順序で進めた
