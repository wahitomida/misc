# AI Orchestra — LLM プロンプト集

> システム内で使用される全プロンプトテンプレートのカタログ

---

## 1. プロンプト設計方針

```
- 日本語で出力を要求する（ユーザー向け表示はすべて日本語）
- JSON出力を要求する場合はスキーマを明示する
- 文字数制限を明示する（50〜150文字のチャットテンポ）
- ロールの性格・専門を system prompt に埋め込む
- コンテキスト（前ラウンドの結論等）を user message に含める
- 禁止事項を明確にする（論文口調禁止、長文禁止）
```

---

## 2. Phase 1: 計画立案 (Orchestrator)

### 2.1 PLANNING_PROMPT

**使用箇所**: `core/orchestrator.py` — `Orchestrator.plan()`
**モデル**: `gpt-5.4` (reasoning model)
**出力形式**: JSON

```python
PLANNING_PROMPT = """\
あなたは研究チームの議論を設計する「議論設計者」です。
ユーザーのテーマに対し、最適な議論計画を立案してください。

## ユーザーのテーマ
{user_input}

## 利用可能なAIロール
{roles_description}

## 制約条件
- 制限時間: {time_limit_sec}秒
- 最大参加AI数: {max_agents}名
- 専門レベル: {expertise}
- 会話トーン: brainstorming（カジュアルな研究議論）

## 設計要件
1. ODSC（目的/成果物/範囲/基準）を定義する
2. 参加AIを選定する（テーマに最適な組み合わせ）
3. ラウンド計画を立案する（2〜5ラウンド）
4. 各AIへの個別指示を作成する

## ラウンド設計のルール
- ラウンド数: 2〜5（時間に応じて。細かく切りすぎない）
- 各ラウンドにはフェーズを設定: diverge（発散）/ deepen（深掘り）/ converge（収束）
- 各ラウンドには発言パターンを設定: one_shot / ping_pong / free_talk
- 各ラウンドの主導者（leader）は speakers[0]
- 主導者がラウンド末尾で他者の意見を踏まえた結論を出す

## 発言パターンの説明
- one_shot: speakers順に各1回発言（発散フェーズ向き）
- ping_pong: 2者が交互に3往復（深掘りフェーズ向き）
- free_talk: 動的に次発言者を決定、最大8発言（収束フェーズ向き）

{follow_up_section}
{scenario_section}

## 出力形式 (JSON)
{{
"odsc": {{
"objective": "<議論の目的 (100文字以内)>",
"deliverables": "<期待される成果物 (100文字以内)>",
"scope": "<議論の範囲 (100文字以内)>",
"criteria": "<成功基準 (100文字以内)>"
}},
"agents": ["<role_id>", ...],
"rounds": [
{{
"number": 1,
"phase": "diverge|deepen|converge",
"pattern": "one_shot|ping_pong|free_talk",
"speakers": ["<role_id>", ...],
"leader": "<role_id>",
"topic": "<このラウンドのテーマ (50文字以内)>",
"level": "concise|standard|detailed"
}}
],
"private_instructions": [
{{
"role_id": "<role_id>",
"instruction": "<このAIへの個別指示 (100文字以内)>"
}}
]
}}
"""
```

### 2.2 フォローアップ追加セクション

```python
FOLLOW_UP_SECTION = """\
## フォローアップ情報
前回セッション ({previous_session_id}) の結論:
{conclusion}

前回の仮説テーブル:
{hypothesis_table}

未解決の論点:
{unresolved}

今回の重点:
{focus_description}

添付資料:
{attachments_summary}

前回の議論を踏まえ、未解決の論点を深掘りする計画を立ててください。
仮説の検証・更新を計画に含めてください。
"""
```

### 2.3 シナリオ追加セクション

```python
SCENARIO_SECTION = """\
## シナリオ: {scenario_name}
推奨構成:
- 推奨ロール: {recommended_roles}
- 推奨ラウンド構成: {recommended_rounds}
- 重点観点: {focus_points}

上記の推奨構成を参考にしつつ、テーマに最適化してください。
"""
```

---

## 3. Phase 2: 議論進行 (Conductor / Agent)

### 3.1 エージェント System Prompt テンプレート

**使用箇所**: `core/agent.py` — `Agent._build_system_prompt()`
**モデル**: 各エージェントの設定モデル

```python
AGENT_SYSTEM_PROMPT = """\
あなたは「{role_name}」({emoji}) です。

## 専門分野
{specialty}

## 性格
{personality}

## 発言ルール
{speaking_rules_formatted}

## 弱み（自覚して改善に努めること）
{weaknesses}

## 重要な制約
- 1回の発言は50〜150文字（チャットのテンポで）
- 論文口調禁止。カジュアルな研究者同士の会話で
- 数式は必要最小限（文中に埋め込む形で）
- 他者の発言を踏まえて建設的に発言する
- 「なるほど」「確かに」だけの発言は禁止
- 必ず自分の専門的視点から新しい情報を追加する

{private_instruction_section}
{feedback_section}
"""
```

### 3.2 エージェント発言リクエスト (User Message)

**使用箇所**: `core/agent.py` — `Agent._build_context_message()`

```python
AGENT_SPEAK_MESSAGE = """\
## 議論テーマ
{theme}

## 現在の状況
- ラウンド {round_num} / {total_rounds}
- フェーズ: {phase}
- あなたの役割: {role_in_round}

## これまでの議論
{context}

## 今回のトピック
{topic}

{additional_instruction}

上記を踏まえ、あなたの専門的視点から発言してください。
50〜150文字で、具体的かつ建設的に。
"""
```

### 3.3 ラウンド結論要求プロンプト

**使用箇所**: `core/conductor.py` — ラウンド末尾で主導者に結論を要求
**モデル**: 議論モデル (gpt-4.1)

```python
ROUND_CONCLUSION_PROMPT = """\
あなたはこのラウンドの主導者です。
他のメンバーの意見を踏まえて、このラウンドの結論をまとめてください。

## このラウンドの発言
{round_utterances}

## 結論のルール
- 100文字以内でまとめる
- 合意点と残課題を明確にする
- 次のラウンドへの橋渡しとなる表現にする
- あなたの専門的視点を活かした結論にする

結論を述べてください:
"""
```

### 3.4 自由発言モード 次話者決定プロンプト

**使用箇所**: `core/conductor.py` — `_decide_next_speaker()`
**モデル**: 議論モデル (gpt-4.1)

```python
NEXT_SPEAKER_PROMPT = """\
議論の次の発言者を決定してください。

## 参加者
{speakers_with_counts}

## 直近の発言
{recent_utterances}

## 選定基準
- まだ発言が少ない人を優先
- 直前の発言に対して最も有効な反応ができる人を選ぶ
- 同じ人が連続しないようにする

## 出力 (JSON)
{{"next_speaker": "<role_id>", "reason": "<理由 30文字以内>"}}
"""
```

### 3.5 方向転換指示プロンプト

**使用箇所**: `core/conductor.py` — `_force_new_topic()`
**モデル**: 議論モデル (gpt-4.1)

```python
PIVOT_PROMPT = """\
議論が停滞しています。新しい論点を提示してください。

## 停滞の状況
{detection_result}

## これまでの議論概要
{discussion_summary}

## 要求
- 現在の議論から自然に移行できる新しい角度を提案
- 50文字以内で具体的に
- 次の発言者 ({next_speaker_name}) が答えやすい問いかけにする

新しい論点:
"""
```

### 3.6 同意しすぎ対策プロンプト

**使用箇所**: `core/conductor.py` — `_handle_excessive_agreement()`
**モデル**: 議論モデル (gpt-4.1)

```python
DEVIL_ADVOCATE_PROMPT = """\
参加者全員が同じ方向に偏っています。
反対意見や見落としている観点を指摘する発言を生成してください。

## 現在の合意方向
{consensus_direction}

## 参加者の発言
{recent_utterances}

## 要求
- 建設的な反論を50〜100文字で
- 「あえて反対の立場から言うと...」のような導入で
- 具体的な懸念や見落としを指摘

反対意見:
"""
```

---

## 4. Phase 2: 検知系プロンプト

### 4.1 収束度チェック

**使用箇所**: `core/conductor.py` — `ConvergenceChecker.check()`
**モデル**: 議論モデル (gpt-4.1)

```python
CONVERGENCE_CHECK_PROMPT = """\
以下の議論ログを読み、議論の収束度を0.0〜1.0で評価してください。

## 収束度の基準
- 0.0〜0.3: 発散中（新しい論点が次々出ている）
- 0.3〜0.6: 議論中（論点が絞られつつある）
- 0.6〜0.8: 収束傾向（合意形成に向かっている）
- 0.8〜1.0: 収束済み（主要合意が形成された）

## このラウンドの発言
{round_utterances}

## 前ラウンドの結論（あれば）
{previous_conclusion}

## 出力 (JSON)
{{"score": <0.0-1.0>, "reason": "<理由 30文字以内>"}}
"""
```

### 4.2 堂々巡り検知

**使用箇所**: `core/conductor.py` — `RepetitionDetector.check_repetition()`
**モデル**: 議論モデル (gpt-4.1)

```python
REPETITION_CHECK_PROMPT = """\
以下の直近{window}発言が内容的に繰り返しになっていないか判定してください。

## 判定基準
- 同じ論点を別の言い方で繰り返している
- 新しい情報や視点が追加されていない
- 議論が前進していない

## 直近の発言
{utterances}

## 出力 (JSON)
{{
"is_repetitive": <true/false>,
"repeated_point": "<繰り返されている論点 (30文字以内、該当なしなら空)>",
"suggestion": "<新しい論点の提案 (50文字以内、該当なしなら空)>"
}}
"""
```

### 4.3 同意過多検知

**使用箇所**: `core/conductor.py` — `AgreementDetector.check_excessive_agreement()`
**モデル**: 議論モデル (gpt-4.1)

```python
AGREEMENT_CHECK_PROMPT = """\
以下の直近{window}発言で、参加者が全員同じ方向に偏りすぎていないか判定してください。

## 判定基準
- 全員が同意・賛同のみで反論がない
- 批判的検討が欠けている
- グループシンク（集団浅慮）の兆候がある

## 直近の発言
{utterances}

## 出力 (JSON)
{{
"is_excessive": <true/false>,
"consensus_direction": "<合意の方向性 (30文字以内、該当なしなら空)>"
}}
"""
```

---

## 5. Phase 3: 評価 (Evaluator / Synthesizer)

### 5.1 自己評価プロンプト

**使用箇所**: `core/evaluator.py` — `Evaluator.request_self_evaluation()`
**モデル**: 統合モデル (gpt-5.4)

```python
SELF_EVALUATION_PROMPT = """\
あなたは「{role_name}」としてこの議論に参加しました。
自分の発言を振り返り、自己評価してください。

## あなたの発言一覧
{my_utterances}

## 議論全体の流れ
{discussion_summary}

## 議論の目的 (ODSC)
{odsc}

## 評価観点
- 論理性: 主張の根拠は明確か
- 独自性: 自分の専門から新しい視点を提供できたか
- 建設性: 他者の発言を踏まえ議論を前に進められたか
- 簡潔性: 50〜150文字の制約内で的確に伝えられたか

## 出力 (JSON)
{{
"scores": {{
"論理性": <1-5>,
"独自性": <1-5>,
"建設性": <1-5>,
"簡潔性": <1-5>
}},
"reasoning": "<評価理由 (50文字以内)>",
"contribution": "<最大の貢献 (50文字以内)>",
"unfinished": "<やり残し (50文字以内)>"
}}
"""
```

### 5.2 他者評価プロンプト

**使用箇所**: `core/evaluator.py` — `Evaluator.request_peer_evaluation()`
**モデル**: 統合モデル (gpt-5.4)

```python
PEER_EVALUATION_PROMPT = """\
あなたは「{evaluator_name}」です。
他の参加者の発言を評価してください。

## 議論ログ
{discussion_log}

## 評価対象
{target_agents}

## 評価基準
各参加者について:
- 5点満点で総合評価
- 特に良かった点を1つ指摘

## 出力 (JSON)
{{
"evaluations": [
{{
"target_role_id": "<role_id>",
"score": <1-5>,
"comment": "<良かった点 (30文字以内)>"
}}
]
}}
"""
```

### 5.3 指揮者評価プロンプト

**使用箇所**: `core/synthesizer.py` — `_generate_orchestrator_evaluation()`
**モデル**: 統合モデル (gpt-5.4)

```python
ORCHESTRATOR_EVALUATION_PROMPT = """\
あなたは議論の指揮者です。全体を俯瞰して評価してください。

## 議論の目的 (ODSC)
{odsc}

## 参加者と各自の自己評価・他者評価
{evaluations_summary}

## 議論ログの概要
{discussion_summary}

## 評価項目
1. 全体品質 (1-5): 議論の質は目的に対して十分か
2. MVP: 最も貢献した参加者は誰か
3. ODSC達成度 (0.0-1.0): 目的・成果物・基準はどの程度達成されたか
4. 各参加者へのフィードバック: 次回改善すべき点
5. 議論プロセスの改善点

## 出力 (JSON)
{{
"overall_quality": <1-5>,
"mvp_role_id": "<role_id>",
"mvp_reason": "<MVP選出理由 (50文字以内)>",
"odsc_achievement": <0.0-1.0>,
"agent_feedback": {{
"<role_id>": "<フィードバック (50文字以内)>"
}},
"improvements": ["<プロセス改善案 (50文字以内)>"]
}}
"""
```

### 5.4 レポート生成プロンプト

**使用箇所**: `core/synthesizer.py` — `_generate_report()`
**モデル**: 統合モデル (gpt-5.4)

```python
REPORT_GENERATION_PROMPT = """\
以下の議論ログと評価結果をもとに、議論レポートを生成してください。

## 議論テーマ
{theme}

## ODSC
{odsc}

## 議論ログ（全ラウンド）
{discussion_log}

## 評価結果
{evaluation_summary}

## レポート形式 (Markdown)
以下のセクションを含めてください:

# 議論レポート: {theme}

## 1. 概要
（議論の概要を3行で）

## 2. 主要な洞察
（議論で得られた主要な知見をリスト形式で）

## 3. 仮説テーブル
| ID | 仮説 | 状態 | 根拠 |
|----|------|------|------|
（議論中に提示された仮説を整理）

## 4. 実験計画
（仮説を検証するための具体的な実験計画）

## 5. 未解決の論点
（今後深掘りすべき点をリスト形式で）

## 6. 次のステップ
（具体的な次のアクションを3つ以内で）

---
専門レベル: {expertise}
（{expertise_instruction}）
"""

EXPERTISE_INSTRUCTIONS = {
"beginner": "初学者にもわかるよう平易な表現で。専門用語には簡単な説明を添えて。",
"intermediate": "研究者レベル。適度に専門用語を使い、論理的に整理して。",
"expert": "専門家向け。数式・論文引用を含めて高密度に。",
}
```

### 5.5 仮説抽出プロンプト

**使用箇所**: `core/synthesizer.py` — `_extract_hypotheses()`
**モデル**: 統合モデル (gpt-5.4)

```python
HYPOTHESIS_EXTRACTION_PROMPT = """\
以下の議論ログから、提示された仮説を抽出してください。

## 議論ログ
{discussion_log}

## 抽出ルール
- 明示的に「仮説」と述べられたもの
- 「〜ではないか」「〜の可能性がある」等の推測
- 検証可能な形で整理する

## 出力 (JSON)
{{
"hypotheses": [
{{
"id": "H1",
"text": "<仮説の内容 (100文字以内)>",
"status": "unverified",
"evidence": "<根拠 (50文字以内)>",
"source_round": <提示されたラウンド番号>
}}
]
}}
"""
```

### 5.6 要約生成プロンプト

**使用箇所**: `core/synthesizer.py` — `_generate_summary()`
**モデル**: 統合モデル (gpt-5.4)

```python
SUMMARY_GENERATION_PROMPT = """\
以下の議論レポートを200文字以内で要約してください。

## レポート
{report}

## 要約のルール
- 結論を最初に述べる
- 主要な仮説/提案を含める
- 次のアクションを含める
- 200文字以内

要約:
"""
```

---

## 6. Phase 3: 全会話ログ整形

### 6.1 全会話ログ生成プロンプト

**使用箇所**: `core/synthesizer.py` — `_generate_full_conversation()`
**注意**: このプロンプトは使わず、テンプレートベースで生成する方が良い

```python
FULL_CONVERSATION_TEMPLATE = """\
# 全会話ログ: {theme}

**日時**: {datetime}
**参加者**: {participants}
**制限時間**: {time_limit}秒

---

## 舞台裏: 計画立案

**ODSC:**
- 🎯 目的: {objective}
- 📦 成果物: {deliverables}
- 🔲 範囲: {scope}
- ✅ 基準: {criteria}

**参加AI選定理由:**
{selection_reasons}

---

{rounds_section}

---

## 評価結果

### MVP: {mvp_emoji} {mvp_name}
> {mvp_reason}

### 全体品質: {'⭐' * overall_quality} ({overall_quality}/5)

---

*セッションID: {session_id}*
*総発言数: {total_utterances} | 総トークン: {total_tokens} | 収束度: {convergence}*
"""

ROUND_TEMPLATE = """\
## Round {round_num}: {topic}
*フェーズ: {phase} | パターン: {pattern} | 主導: {leader_emoji}{leader_name}*

{utterances_section}

### 🎯 Round {round_num} 結論 (by {concluder_emoji}{concluder_name})
> {conclusion}

*収束度: {convergence_score} | 所要時間: {duration_sec:.1f}秒*

---
"""

UTTERANCE_TEMPLATE = """\
**{emoji} {role_name}:**
{content}

"""
```

---

## 7. メモリ管理プロンプト

### 7.1 ラウンド要約プロンプト

**使用箇所**: `core/memory.py` — `ConversationMemory.summarize_round()`
**モデル**: `gpt-4.1` (軽量)

```python
ROUND_SUMMARY_PROMPT = """\
以下のラウンドの議論を50文字以内で要約してください。
結論と重要な論点のみ含めてください。

## ラウンド{round_num}の発言
{utterances}

## 結論
{conclusion}

要約 (50文字以内):
"""
```

---

## 8. Code Review 専用プロンプト

### 8.1 構造スキャンプロンプト

**使用箇所**: `features/code_review/scanner.py`
**モデル**: 計画モデル (gpt-5.4)

```python
STRUCTURE_SCAN_PROMPT = """\
以下のプロジェクト構造を分析し、レビュー計画を立ててください。

## ファイルツリー
{file_tree}

## ファイル情報
{file_summaries}

## 出力 (JSON)
{{
"project_type": "<種類 (ML/web/CLI/library)>",
"entry_points": ["<エントリポイントファイル>"],
"core_modules": ["<コアモジュール>"],
"test_coverage": "<テストの有無と充実度>",
"review_priority": ["<優先レビュー対象ファイル>"]
}}
"""
```

### 8.2 パートリーダー調査プロンプト (6種)

**使用箇所**: `features/code_review/part_leader.py`
**モデル**: 議論モデル (gpt-4.1)

```python
INVESTIGATION_PROMPTS = {
"algorithm": """\
以下のコードをアルゴリズムの観点から分析してください。

## 分析対象
{code_content}

## チェック項目
- 数式とコードの対応は正しいか
- 境界条件は適切に処理されているか
- 数値安定性に問題はないか
- 計算量は妥当か

## 出力 (JSON)
{{"findings": [{{"severity": "critical|major|minor|suggestion", "title": "...", "description": "...", "file_path": "...", "line_range": [start, end], "suggestion": "..."}}]}}
""",

"reproducibility": """\
以下のコードを再現性の観点から分析してください。

## 分析対象
{code_content}

## チェック項目
- 乱数シードは固定可能か
- 設定ファイルで実験条件が管理されているか
- 環境依存（パス、バージョン）はないか
- データの前処理は決定的か

## 出力 (JSON)
{{"findings": [{{"severity": "...", "title": "...", "description": "...", "file_path": "...", "line_range": [start, end], "suggestion": "..."}}]}}
""",

"performance": """\
以下のコードを性能の観点から分析してください。

## 分析対象
{code_content}

## チェック項目
- ボトルネックとなる処理はないか
- メモリ使用量は妥当か
- 並列化の余地はあるか
- 不要な計算の繰り返しはないか

## 出力 (JSON)
{{"findings": [{{"severity": "...", "title": "...", "description": "...", "file_path": "...", "line_range": [start, end], "suggestion": "..."}}]}}
""",

"structure": """\
以下のコードを構造・設計の観点から分析してください。

## 分析対象
{code_content}

## チェック項目
- モジュール分割は適切か
- DRY原則は守られているか
- SOLID原則への適合度
- 依存関係は整理されているか

## 出力 (JSON)
{{"findings": [{{"severity": "...", "title": "...", "description": "...", "file_path": "...", "line_range": [start, end], "suggestion": "..."}}]}}
""",

"readability": """\
以下のコードを可読性の観点から分析してください。

## 分析対象
{code_content}

## チェック項目
- 変数名・関数名は意味を伝えているか
- docstring は十分か
- 型ヒントは付いているか
- コメントは適切か（過不足）

## 出力 (JSON)
{{"findings": [{{"severity": "...", "title": "...", "description": "...", "file_path": "...", "line_range": [start, end], "suggestion": "..."}}]}}
""",

"results": """\
以下のコードを出力・結果の観点から分析してください。

## 分析対象
{code_content}

## チェック項目
- 出力結果の妥当性は検証されているか
- 論文の記載と整合しているか
- テストは十分か
- エッジケースは考慮されているか

## 出力 (JSON)
{{"findings": [{{"severity": "...", "title": "...", "description": "...", "file_path": "...", "line_range": [start, end], "suggestion": "..."}}]}}
""",
}
```

### 8.3 相互質問プロンプト

**使用箇所**: `features/code_review/cross_question.py`
**モデル**: 議論モデル (gpt-4.1)

```python
CROSS_QUESTION_PROMPT = """\
あなたは「{questioner_aspect}」の観点でコードをレビューしました。
「{target_aspect}」担当の分析結果を読み、質問してください。

## あなたの分析結果
{my_findings}

## 相手の分析結果
{target_findings}

## 質問のルール
- 自分の観点から見て気になる点を質問する
- 相手の指摘と自分の指摘の矛盾があれば指摘する
- 100文字以内で具体的に

質問:
"""

CROSS_ANSWER_PROMPT = """\
あなたは「{answerer_aspect}」の観点でコードをレビューしました。
「{questioner_aspect}」担当からの質問に回答してください。

## 質問
{question}

## あなたの分析結果
{my_findings}

## 回答のルール
- 100文字以内で具体的に
- 必要なら自分の指摘を修正する

回答:
"""
```

### 8.4 Vibe Coding Prompt 生成

**使用箇所**: `core/synthesizer.py` — `_generate_vibe_prompt()`
**モデル**: 統合モデル (gpt-5.4)

```python
VIBE_CODING_PROMPT_GENERATION = """\
以下のコードレビュー結果をもとに、AIコーディングツール向けの修正指示書を生成してください。

## レビュー結果
{findings_summary}

## プロジェクト構造
{project_structure}

## 指示書の形式 (Markdown)

# 修正指示書

## 優先度: Critical
（すぐに修正すべき問題）

### 1. [ファイル名] — [問題タイトル]
- 問題: ...
- 修正方法: ...
- 対象行: ...

## 優先度: Major
（次に修正すべき問題）
...

## 優先度: Minor / Suggestion
（時間があれば対応）
...

---
注意事項:
- 各修正は独立して適用可能にする
- コード例を含める場合は最小限に
- 修正後の期待動作を明記する
"""
```

---

## 9. フォローアップ専用プロンプト

### 9.1 議論圧縮プロンプト

**使用箇所**: `core/follow_up.py` — `FollowUpManager._compress_discussion()`
**モデル**: `gpt-4.1`

```python
COMPRESS_DISCUSSION_PROMPT = """\
以下の議論ログを300文字以内に圧縮してください。
次回の議論で参照するためのコンテキストとして使います。

## 議論ログ
{full_conversation}

## 圧縮ルール
- 主要な結論と合意点を優先
- 具体的な手法名・数値は保持
- 議論の流れ（発散→深掘り→収束）を簡潔に
- 300文字以内

圧縮版:
"""
```

---

## 10. プロンプト設計のベストプラクティス

### 10.1 JSON 出力の確実性

```python
# ✅ Good: スキーマを明示 + 例を提供
"""
## 出力 (JSON)
{{
"score": <0.0-1.0>,
"reason": "<理由 30文字以内>"
}}

例:
{{"score": 0.72, "reason": "論点が絞られつつあるが合意には至っていない"}}
"""

# ❌ Bad: 曖昧な指示
"""
JSONで出力してください。
"""
```

### 10.2 文字数制限の効果

```python
# ✅ Good: 明確な制限 + 用途
"""
50〜150文字で、チャットのテンポで発言してください。
"""

# ❌ Bad: 制限なし（長文になりがち）
"""
発言してください。
"""
```

### 10.3 禁止事項の明示

```python
# ✅ Good: 具体的な禁止
"""
## 禁止事項
- 「なるほど」「確かに」だけの発言
- 論文調の硬い表現
- 200文字を超える発言
- 前の人の発言をそのまま繰り返すこと
"""
```

### 10.4 コンテキスト量の制御

```python
# ✅ Good: 必要なコンテキストのみ提供
"""
## 前ラウンドの結論
{previous_conclusion}

## 今ラウンドの発言（あなたの番まで）
{current_round_utterances}
"""

# ❌ Bad: 全履歴を毎回送信（トークン浪費）
"""
## 全議論ログ
{entire_discussion_history}  # 数千トークン
"""
```

---

## 11. プロンプトのバージョン管理

```python
# 各プロンプトにバージョンを付与
PLANNING_PROMPT_V = "1.0"
AGENT_SYSTEM_PROMPT_V = "1.0"
CONVERGENCE_CHECK_PROMPT_V = "1.0"

# 将来: A/Bテストで改善
# PLANNING_PROMPT_V2 = "..." (新バージョンの候補)