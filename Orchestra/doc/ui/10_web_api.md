# AI Orchestra — Web API エンドポイント設計

> フロントエンドとバックエンドを接続する全APIの詳細仕様

---

## 1. API 設計方針

| 原則 | 説明 |
|------|------|
| **RESTful** | リソースベースのURL設計 |
| **JSON統一** | リクエスト/レスポンスは全てJSON (SSE除く) |
| **エラー形式統一** | `{"detail": "エラーメッセージ"}` |
| **バリデーション** | Pydantic BaseModel で入力検証 |
| **ページネーション** | `page` + `limit` パラメータ方式 |
| **冪等性** | GET/DELETE は冪等、POST は非冪等 |

---

## 2. 共通仕様

### 2.1 ベースURL

```
http://localhost:8080/api/
```

### 2.2 リクエストヘッダー

| ヘッダー | 値 | 用途 |
|---------|-----|------|
| `Content-Type` | `application/json` | POST リクエスト |
| `Accept` | `application/json` or `text/event-stream` | レスポンス形式指定 |

### 2.3 エラーレスポンス形式

```json
// 422 Validation Error (Pydantic)
{
"detail": [
{
"loc": ["body", "prompt"],
"msg": "ensure this value has at least 5 characters",
"type": "value_error"
}
]
}

// 400/404/500 等
{
"detail": "エラーメッセージ"
}
```

### 2.4 HTTPステータスコード

| コード | 意味 | 使用場面 |
|--------|------|---------|
| 200 | 成功 | 通常レスポンス |
| 201 | 作成 | (使用しない) |
| 400 | 不正リクエスト | パラメータ不正 |
| 404 | 未検出 | セッション/ロールが存在しない |
| 422 | バリデーションエラー | Pydantic 検証失敗 |
| 429 | レートリミット | 同時セッション上限 |
| 500 | サーバーエラー | 予期しないエラー |

---

## 3. Idea API

### 3.1 POST /api/idea/plan

計画立案のみ実行し、結果をJSONで返す。ユーザーが確認後にstreamを呼ぶ。

**Request:**

```json
{
"prompt": "LLMの推論効率を改善する手法を議論して",
"planner_model": "gpt-5.4",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 300,
"max_agents": 5,
"expertise": "intermediate",
"follow_up_id": null,
"attached_files": []
}
```

| フィールド | 型 | 必須 | デフォルト | バリデーション |
|-----------|-----|------|-----------|--------------|
| `prompt` | string | ✅ | — | 5〜5000文字 |
| `planner_model` | string | — | `"gpt-5.4"` | — |
| `conductor_model` | string | — | `"gpt-4.1"` | — |
| `synth_model` | string | — | `"gpt-5.4"` | — |
| `time_limit` | int | — | `300` | 60〜1800 |
| `max_agents` | int | — | `5` | 2〜8 |
| `expertise` | string | — | `"intermediate"` | "beginner"/"intermediate"/"expert" |
| `follow_up_id` | string\|null | — | `null` | 存在するセッションID |
| `attached_files` | list[string] | — | `[]` | 最大5件 |

**Response (200):**

```json
{
"plan": {
"theme": "LLMの推論効率を改善する手法を議論して",
"odsc": {
"objective": "LLM推論の効率化手法を多角的に検討する",
"deliverables": "具体的手法リスト + 実験計画",
"scope": "Transformer系モデルの推論時最適化",
"criteria": "3つ以上の具体手法が提案され、実験計画がある"
},
"agents": [
{
"role_id": "theorist",
"emoji": "🧮",
"name": "理論屋",
"specialty": "数学的定式化、計算量解析、収束証明"
},
{
"role_id": "experimentalist",
"emoji": "🔬",
"name": "実験屋",
"specialty": "実験設計、検証計画、再現性"
}
],
"rounds": [
{
"number": 1,
"phase": "diverge",
"pattern": "one_shot",
"speakers": ["theorist", "experimentalist", "implementer"],
"leader": "theorist",
"topic": "推論効率改善のアプローチ列挙",
"estimated_sec": 60,
"level": "standard"
}
],
"private_instructions": [
{
"role_id": "theorist",
"instruction": "計算量の理論的下界を意識して議論をリードせよ"
}
]
},
"estimated_requests": 36,
"remaining_quota": 9964
}
```

**Error (422):**

```json
{
"detail": [
{
"loc": ["body", "prompt"],
"msg": "ensure this value has at least 5 characters",
"type": "value_error.any_str.min_length"
}
]
}
```

---

### 3.2 POST /api/idea/stream

計画を受け取り、Phase 2〜3 を実行しながらSSEでイベントを送信。

**Request:**

```json
{
"plan": { "...OrchestraPlan (上記plan応答と同じ構造)..." },
"prompt": "LLMの推論効率を改善する手法を議論して",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 300,
"expertise": "intermediate"
}
```

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `plan` | dict | ✅ | 確認済みの計画 (plan応答をそのまま) |
| `prompt` | string | ✅ | 元テーマ |
| `conductor_model` | string | — | 議論進行モデル |
| `synth_model` | string | — | 統合モデル |
| `time_limit` | int | — | 制限時間(秒) |
| `expertise` | string | — | 専門レベル |

**Response:**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

data: {"type": "round_start", "round": 1, "config": {...}}\n\n
data: {"type": "utterance", "round": 1, "agent": {...}, "content": "...", "tokens": 150}\n\n
data: {"type": "round_conclusion", "round": 1, "concluder": "theorist", "content": "..."}\n\n
data: {"type": "round_end", "round": 1, "convergence": 0.72, "elapsed_sec": 45.2}\n\n
...
data: {"type": "synthesis_start"}\n\n
data: {"type": "done", "session_id": "20260622_133204_idea", "statistics": {...}}\n\n
```

**Error (429):**

```json
{
"detail": "同時実行セッション数の上限です。しばらくお待ちください。"
}
```

---

## 4. Review API

### 4.1 POST /api/review/plan

スキャンと計画立案を実行し、結果を返す。

**Request:**

```json
{
"target_path": "./src",
"planner_model": "gpt-5.4",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 600,
"max_agents": 6,
"focus": "all",
"ignore_patterns": ["__pycache__", "*.pyc"]
}
```

| フィールド | 型 | 必須 | デフォルト | バリデーション |
|-----------|-----|------|-----------|--------------|
| `target_path` | string | ✅ | — | 存在するディレクトリ |
| `planner_model` | string | — | `"gpt-5.4"` | — |
| `conductor_model` | string | — | `"gpt-4.1"` | — |
| `synth_model` | string | — | `"gpt-5.4"` | — |
| `time_limit` | int | — | `600` | 60〜1800 |
| `max_agents` | int | — | `6` | 2〜8 |
| `focus` | string | — | `"all"` | "all"/"pre_submission"/"performance"/"structure"/"handover"/"algorithm" |
| `ignore_patterns` | list[string] | — | `[]` | — |

**Response (200):**

```json
{
"scan_result": {
"root_path": "./src",
"total_files": 12,
"total_lines": 1540,
"languages": {"python": 10, "yaml": 2},
"tree_text": "src/\n├── main.py\n├── core/\n│   ├── agent.py\n...",
"files": [
{
"path": "src/main.py",
"extension": ".py",
"size_bytes": 1250,
"lines": 45,
"header": "import typer\nfrom core..."
}
]
},
"part_leaders": [
{
"aspect": "algorithm",
"aspect_label": "アルゴリズム",
"role_id": "theorist",
"role_name": "理論屋",
"emoji": "🧮",
"files": ["core/agent.py", "core/conductor.py"]
}
],
"estimated_requests": 60,
"remaining_quota": 9940
}
```

---

### 4.2 POST /api/review/stream

レビューの Phase 2〜5 を実行しながらSSEでイベントを送信。

**Request:**

```json
{
"scan_result": { "...上記scan_result..." },
"part_leaders": [ "...上記part_leaders..." ],
"target_path": "./src",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 600,
"focus": "all"
}
```

**Response (SSE):**

```
data: {"type": "investigation_start", "aspect": "algorithm", "emoji": "🧮"}\n\n
data: {"type": "investigation_progress", "aspect": "algorithm", "progress": 50}\n\n
data: {"type": "investigation_finding", "aspect": "algorithm", "finding": {...}}\n\n
data: {"type": "investigation_complete", "aspect": "algorithm", "findings_count": 3}\n\n
data: {"type": "cross_question_start"}\n\n
data: {"type": "cross_question", "questioner": "structure", "target": "algorithm", ...}\n\n
data: {"type": "cross_answer", "answerer": "algorithm", ...}\n\n
data: {"type": "cross_question_complete"}\n\n
data: {"type": "meeting_start"}\n\n
data: {"type": "round_start", "round": 1, "config": {...}}\n\n
data: {"type": "utterance", ...}\n\n
...
data: {"type": "done", "session_id": "20260622_140000_review", "statistics": {...}}\n\n
```

---

## 5. Sessions API

### 5.1 GET /api/sessions

セッション一覧を返す (ページネーション付き)。

**Query Parameters:**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `page` | int | `1` | ページ番号 (1始まり) |
| `limit` | int | `10` | 1ページの件数 (max: 50) |
| `type` | string\|null | `null` | "idea" or "review" でフィルタ |
| `search` | string\|null | `null` | テーマ部分一致検索 |
| `sort` | string | `"date_desc"` | ソート順 |
| `show_chains` | bool | `false` | チェーン情報を含める |

**sort の選択肢:**

| 値 | 説明 |
|----|------|
| `date_desc` | 新しい順 (デフォルト) |
| `date_asc` | 古い順 |
| `duration_desc` | 時間が長い順 |
| `convergence_desc` | 収束度が高い順 (ideaのみ有効) |

**Response (200):**

```json
{
"sessions": [
{
"id": "20260622_133204_idea",
"type": "idea",
"theme": "LLMの推論効率を改善する手法を議論して",
"date": "2026-06-22T13:32:04",
"duration_sec": 272.5,
"convergence": 0.87,
"mvp_role_id": "theorist",
"mvp_emoji": "🧮",
"focus": null,
"chain_depth": 0,
"agents_count": 5,
"rounds_completed": 3
},
{
"id": "20260621_091545_review",
"type": "review",
"theme": "src/ のコードレビュー",
"date": "2026-06-21T09:15:45",
"duration_sec": 598.2,
"convergence": null,
"mvp_role_id": null,
"mvp_emoji": null,
"focus": "all",
"chain_depth": 0,
"agents_count": 6,
"rounds_completed": 3
}
],
"total": 25,
"page": 1,
"pages": 3,
"chains": [
[
{"id": "20260620_100000_idea", "date": "2026-06-20T10:00:00", "theme": "..."},
{"id": "20260621_140000_idea", "date": "2026-06-21T14:00:00", "theme": "..."},
{"id": "20260622_133204_idea", "date": "2026-06-22T13:32:04", "theme": "..."}
]
]
}
```

---

### 5.2 GET /api/sessions/recent

最新N件のセッションを返す (ホームページ用の軽量版)。

**Query Parameters:**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `limit` | int | `5` | 取得件数 |
| `type` | string\|null | `null` | タイプフィルタ |

**Response (200):**

```json
{
"sessions": [
{
"id": "20260622_133204_idea",
"type": "idea",
"theme": "LLMの推論効率を改善する手法を議論して",
"date": "2026-06-22T13:32:04",
"duration_sec": 272.5
}
],
"total": 25,
"page": 1,
"pages": 1
}
```

---

### 5.3 GET /api/sessions/{session_id}

セッションのメタ情報 (session_meta.json の内容) を返す。

**Response (200):**

```json
{
"id": "20260622_133204_idea",
"type": "idea",
"theme": "LLMの推論効率を改善する手法を議論して",
"created_at": "2026-06-22T13:32:04",
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
"duration_sec": 272.5,
"total_utterances": 14,
"total_tokens": 2850,
"total_requests": 36,
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

**Error (404):**

```json
{
"detail": "Session not found: 20260622_133204_idea"
}
```

---

### 5.4 GET /api/sessions/{session_id}/content

セッションの全出力ファイル内容を返す。

**Response (200):**

```json
{
"session_id": "20260622_133204_idea",
"files": {
"report": "# 議論レポート: LLMの推論効率を改善する手法\n\n## 1. 概要\n...",
"conversation": "# 全会話ログ\n\n## 舞台裏: 計画立案\n...",
"evaluation": "# 評価結果\n\n## 自己評価\n...",
"summary": "LLM推論の効率化について5名のAIが議論し、KV-cache圧縮とバッチ最適化の2軸が有望という結論に至った。",
"vibe_prompt": null
},
"chain": [
"20260622_133204_idea"
],
"hypotheses": [
{
"id": "H1",
"text": "KV-cache圧縮により推論速度が30%向上する",
"status": "unverified",
"evidence": "理論的な計算量削減から推定",
"source_round": 1
},
{
"id": "H2",
"text": "バッチサイズ最適化でスループットが2倍になる",
"status": "unverified",
"evidence": "実装屋の経験則に基づく",
"source_round": 2
}
]
}
```

**review セッションの場合:**

```json
{
"session_id": "20260621_091545_review",
"files": {
"report": "# コードレビューレポート\n\n## 1. 概要\n...",
"conversation": "# 全体会議ログ\n\n## Round 1: 課題報告\n...",
"evaluation": "# 評価結果\n...",
"summary": "src/ ディレクトリの12ファイルをレビューし...",
"vibe_prompt": "# 修正指示書\n\n## 優先度: Critical\n\n### 1. core/agent.py — 境界条件チェック欠落\n..."
},
"chain": ["20260621_091545_review"],
"hypotheses": null
}
```

---

### 5.5 GET /api/sessions/{session_id}/download

セッションファイルをダウンロードする。

**Query Parameters:**

| パラメータ | 型 | デフォルト | 選択肢 |
|-----------|-----|-----------|--------|
| `file` | string | `"report"` | "report" / "conversation" / "evaluation" / "summary" / "vibe_prompt" / "all" |

**Response (file != "all"):**

```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="20260622_133204_idea_report.md"

(ファイル内容)
```

**Response (file == "all"):**

```
Content-Type: application/zip
Content-Disposition: attachment; filename="20260622_133204_idea.zip"

(ZIPファイル)
```

**ZIP内容:**

```
20260622_133204_idea/
├── session_meta.json
├── discussion.json
├── full_conversation.md
├── report.md
├── evaluation.md
├── summary.txt
└── vibe_coding_prompt.md  (reviewのみ)
```

---

### 5.6 DELETE /api/sessions/{session_id}

セッションを削除する (ディレクトリごと削除)。

**Response (200):**

```json
{
"status": "deleted",
"session_id": "20260622_133204_idea"
}
```

**Error (404):**

```json
{
"detail": "Session not found: 20260622_133204_idea"
}
```

---

## 6. Roles API

### 6.1 GET /api/roles

全ロール一覧を返す (統計サマリー付き)。

**Response (200):**

```json
[
{
"id": "theorist",
"name": "理論屋",
"emoji": "🧮",
"specialty": "数学的定式化、計算量解析、収束証明",
"stats": {
"session_count": 8,
"avg_score": 4.1,
"mvp_count": 3,
"trend": "improving"
}
},
{
"id": "experimentalist",
"name": "実験屋",
"emoji": "🔬",
"specialty": "実験設計、検証計画、再現性",
"stats": {
"session_count": 6,
"avg_score": 3.8,
"mvp_count": 1,
"trend": "stable"
}
},
{
"id": "implementer",
"name": "実装屋",
"emoji": "🤖",
"specialty": "実装可能性、性能、並列化",
"stats": {
"session_count": 7,
"avg_score": 4.5,
"mvp_count": 2,
"trend": "improving"
}
},
{
"id": "literature",
"name": "文献屋",
"emoji": "📚",
"specialty": "関連研究、引用、先行事例",
"stats": {
"session_count": 5,
"avg_score": 4.0,
"mvp_count": 0,
"trend": "stable"
}
},
{
"id": "devil",
"name": "穴探し",
"emoji": "😈",
"specialty": "反論、弱点指摘、限界指摘",
"stats": {
"session_count": 6,
"avg_score": 4.1,
"mvp_count": 1,
"trend": "stable"
}
},
{
"id": "bird_eye",
"name": "鳥の目",
"emoji": "🎯",
"specialty": "俯瞰、方向修正、全体整合",
"stats": {
"session_count": 8,
"avg_score": 4.3,
"mvp_count": 2,
"trend": "improving"
}
},
{
"id": "code_architect",
"name": "設計リーダー",
"emoji": "📐",
"specialty": "モジュール分割、DRY、SOLID",
"stats": {
"session_count": 4,
"avg_score": 3.9,
"mvp_count": 1,
"trend": "stable"
}
},
{
"id": "code_reviewer",
"name": "可読性リーダー",
"emoji": "📝",
"specialty": "命名、docstring、型ヒント",
"stats": {
"session_count": 3,
"avg_score": 4.0,
"mvp_count": 0,
"trend": "stable"
}
}
]
```

---

### 6.2 GET /api/roles/{role_id}

ロールの詳細情報を返す。

**Response (200):**

```json
{
"id": "theorist",
"name": "理論屋",
"emoji": "🧮",
"specialty": "数学的定式化、計算量解析、収束証明",
"personality": "厳密・論理的。数式で語りたがる",
"weaknesses": "実装コストを軽視しがち",
"speaking_rules": [
"主張には必ず計算量や証明の根拠を添える",
"他者の直感的主張を数式で再解釈する",
"実装不可能な理論に走りすぎない"
]
}
```

**Error (404):**

```json
{
"detail": "Role not found: unknown_role"
}
```

---

### 6.3 GET /api/roles/{role_id}/stats

ロール別パフォーマンス統計を返す。

**Response (200):**

```json
{
"role_id": "theorist",
"session_count": 8,
"self_avg": 4.2,
"peer_avg": 4.0,
"mvp_count": 3,
"trend": "improving",
"history": [
{
"session_id": "20260618_100000_idea",
"date": "2026-06-18",
"topic": "Transformer最適化...",
"self_eval_avg": 3.8,
"peer_eval_avg": 3.5
},
{
"session_id": "20260620_140000_idea",
"date": "2026-06-20",
"topic": "Attention機構...",
"self_eval_avg": 4.5,
"peer_eval_avg": 4.3
},
{
"session_id": "20260622_133204_idea",
"date": "2026-06-22",
"topic": "LLM推論効率...",
"self_eval_avg": 4.2,
"peer_eval_avg": 4.0
}
],
"recent_feedback": [
{
"session_id": "20260622_133204_idea",
"date": "2026/06/22",
"topic": "LLM推論効率...",
"self_eval_avg": 4.2,
"peer_eval_avg": 4.0,
"orchestrator_feedback": "もう少し具体例を交えて説明すると良い"
},
{
"session_id": "20260620_140000_idea",
"date": "2026/06/20",
"topic": "Attention機構...",
"self_eval_avg": 4.5,
"peer_eval_avg": 4.3,
"orchestrator_feedback": "数式の展開が丁寧で良い"
}
]
}
```

**Response (統計なし):**

```json
{
"role_id": "theorist",
"session_count": 0,
"self_avg": 0.0,
"peer_avg": 0.0,
"mvp_count": 0,
"trend": "stable",
"history": [],
"recent_feedback": []
}
```

---

## 7. Health API

### 7.1 GET /api/health

API接続の健全性を確認する。

**Response (200 — 正常):**

```json
{
"status": "ok",
"mode": "openai",
"model_available": true,
"rate_limit_remaining": 9850,
"rate_limit_daily": 10000,
"active_sessions": 0,
"max_sessions": 3,
"version": "1.0.0"
}
```

**Response (200 — 劣化):**

```json
{
"status": "degraded",
"mode": "openai",
"model_available": false,
"error": "Model gpt-5.4 not responding",
"rate_limit_remaining": 9850,
"rate_limit_daily": 10000,
"active_sessions": 1,
"max_sessions": 3,
"version": "1.0.0"
}
```

---

## 8. バックエンド実装パターン

### 8.1 ルーター登録 (web/app.py)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routes import pages, api_idea, api_review, api_sessions, api_roles

app = FastAPI(title="AI Orchestra", version="1.0.0")

# 静的ファイル
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# テンプレート
templates = Jinja2Templates(directory="web/templates")

# ルーター
app.include_router(pages.router)
app.include_router(api_idea.router, tags=["idea"])
app.include_router(api_review.router, tags=["review"])
app.include_router(api_sessions.router, tags=["sessions"])
app.include_router(api_roles.router, tags=["roles"])


# エラーハンドラ
@app.exception_handler(404)
async def not_found_handler(request, exc):
if request.url.path.startswith("/api/"):
return JSONResponse(status_code=404, content={"detail": "Not found"})
return templates.TemplateResponse("pages/404.html", {"request": request}, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request, exc):
if request.url.path.startswith("/api/"):
return JSONResponse(status_code=500, content={"detail": "Internal server error"})
return templates.TemplateResponse("pages/500.html", {"request": request}, status_code=500)
```

### 8.2 依存注入 (web/deps.py)

```python
"""Web UI の依存注入。"""

from functools import lru_cache
from pathlib import Path

from core.config_loader import Settings
from core.api_client import ResilientAPIClient
from core.rate_tracker import RateLimitTracker
from core.role_manager import RoleManager
from core.feedback import FeedbackManager


@lru_cache()
def get_settings() -> Settings:
"""設定を取得する (シングルトン)。"""
return Settings.load()


@lru_cache()
def get_rate_tracker() -> RateLimitTracker:
"""レートトラッカーを取得する (シングルトン)。"""
settings = get_settings()
return RateLimitTracker(
daily_limit=settings.api.daily_limit,
persistence_path=Path(settings.output_dir) / ".rate_limit.json",
)


def get_api_client() -> ResilientAPIClient:
"""APIクライアントを取得する。"""
settings = get_settings()
rate_tracker = get_rate_tracker()
return ResilientAPIClient(
settings=settings,
rate_tracker=rate_tracker,
)


@lru_cache()
def get_role_manager() -> RoleManager:
"""ロールマネージャーを取得する (シングルトン)。"""
settings = get_settings()
return RoleManager(Path(settings.roles_dir))


@lru_cache()
def get_feedback_manager() -> FeedbackManager:
"""フィードバックマネージャーを取得する (シングルトン)。"""
settings = get_settings()
return FeedbackManager(Path(settings.roles_dir))
```

### 8.3 Pydantic モデル定義

```python
"""Web API のリクエスト/レスポンスモデル。"""

from pydantic import BaseModel, Field
from typing import Literal


# === Idea ===

class IdeaPlanRequest(BaseModel):
prompt: str = Field(..., min_length=5, max_length=5000)
planner_model: str = Field("gpt-5.4")
conductor_model: str = Field("gpt-4.1")
synth_model: str = Field("gpt-5.4")
time_limit: int = Field(300, ge=60, le=1800)
max_agents: int = Field(5, ge=2, le=8)
expertise: Literal["beginner", "intermediate", "expert"] = "intermediate"
follow_up_id: str | None = None
attached_files: list[str] = Field(default_factory=list, max_length=5)


class IdeaStreamRequest(BaseModel):
plan: dict
prompt: str
conductor_model: str = "gpt-4.1"
synth_model: str = "gpt-5.4"
time_limit: int = Field(300, ge=60, le=1800)
expertise: str = "intermediate"


# === Review ===

class ReviewPlanRequest(BaseModel):
target_path: str
planner_model: str = "gpt-5.4"
conductor_model: str = "gpt-4.1"
synth_model: str = "gpt-5.4"
time_limit: int = Field(600, ge=60, le=1800)
max_agents: int = Field(6, ge=2, le=8)
focus: Literal["all", "pre_submission", "performance", "structure", "handover", "algorithm"] = "all"
ignore_patterns: list[str] = Field(default_factory=list)


class ReviewStreamRequest(BaseModel):
scan_result: dict
part_leaders: list[dict]
target_path: str
conductor_model: str = "gpt-4.1"
synth_model: str = "gpt-5.4"
time_limit: int = Field(600, ge=60, le=1800)
focus: str = "all"


# === Response Models ===

class SessionSummary(BaseModel):
id: str
type: str
theme: str
date: str
duration_sec: float | None = None
convergence: float | None = None
mvp_role_id: str | None = None
mvp_emoji: str | None = None
focus: str | None = None
chain_depth: int = 0
agents_count: int = 0
rounds_completed: int = 0


class SessionListResponse(BaseModel):
sessions: list[SessionSummary]
total: int
page: int
pages: int
chains: list[list[dict]] | None = None


class HealthResponse(BaseModel):
status: str
mode: str
model_available: bool
rate_limit_remaining: int
rate_limit_daily: int
active_sessions: int
max_sessions: int
version: str
```

---

## 9. CORS 設定

```python
from fastapi.middleware.cors import CORSMiddleware

# 開発時のみ有効
if settings.debug:
app.add_middleware(
CORSMiddleware,
allow_origins=["http://localhost:3000", "http://localhost:8080"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)
```

---

## 10. フロントエンドからの呼び出しパターン

### 10.1 通常のAPI呼び出し (fetch)

```javascript
/**
* APIを呼び出す汎用ヘルパー。
*
* @param {string} url - APIエンドポイント
* @param {object} options - fetch オプション
* @returns {Promise<object>} レスポンスJSON
* @throws {Error} HTTPエラー時
*/
async function apiCall(url, options = {}) {
const defaults = {
headers: { 'Content-Type': 'application/json' },
};
const config = { ...defaults, ...options };

const response = await fetch(url, config);

if (!response.ok) {
let errorMessage;
try {
const data = await response.json();
errorMessage = data.detail || JSON.stringify(data);
} catch {
errorMessage = `HTTP ${response.status}`;
}
throw new Error(errorMessage);
}

return response.json();
}

// 使用例
async function loadSessions(page, limit, type) {
const params = new URLSearchParams({ page, limit, ...(type && { type }) });
return apiCall(`/api/sessions?${params}`);
}

async function createPlan(prompt, settings) {
return apiCall('/api/idea/plan', {
method: 'POST',
body: JSON.stringify({ prompt, ...settings }),
});
}

async function deleteSession(sessionId) {
return apiCall(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}
```

### 10.2 SSE呼び出し

```javascript
// OrchestraSSE クラスを使用 (doc/ui/08_sse_realtime.md 参照)
const sse = new OrchestraSSE('/api/idea/stream');
sse.on('utterance', handleUtterance);
sse.on('done', handleDone);
sse.on('error', handleError);
await sse.start(requestBody);
```

### 10.3 ファイルダウンロード

```javascript
function downloadFile(sessionId, fileType) {
const url = `/api/sessions/${sessionId}/download?file=${fileType}`;
// <a> タグ生成でダウンロード
const a = document.createElement('a');
a.href = url;
a.download = '';
document.body.appendChild(a);
a.click();
document.body.removeChild(a);
}
```

---

## 11. レートリミット・同時実行制御

### 11.1 同時SSEセッション制限

```python
import asyncio

# グローバル: 最大同時SSEセッション数
MAX_CONCURRENT_SESSIONS = 3
_session_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)
_active_count = 0


@router.post("/api/idea/stream")
async def stream_idea_discussion(request: IdeaStreamRequest):
global _active_count

if _active_count >= MAX_CONCURRENT_SESSIONS:
raise HTTPException(
status_code=429,
detail="同時実行セッション数の上限です。しばらくお待ちください。"
)

_active_count += 1
try:
return StreamingResponse(
_event_generator(request),
media_type="text/event-stream",
headers=_SSE_HEADERS,
)
finally:
_active_count -= 1
```

### 11.2 APIクォータチェック

```python
@router.post("/api/idea/plan")
async def create_plan(request: IdeaPlanRequest):
rate_tracker = get_rate_tracker()

# クォータチェック
estimated = _estimate_requests(request)
if not rate_tracker.can_proceed(estimated):
raise HTTPException(
status_code=429,
detail=f"APIクォータ不足。残り: {rate_tracker.remaining()}, 必要: {estimated}"
)

# 計画立案実行
plan = await _execute_planning(request)

return {
"plan": plan.to_dict(),
"estimated_requests": estimated,
"remaining_quota": rate_tracker.remaining(),
}
```

---

## 12. API テスト

### 12.1 テスト構成

```python
# tests/web/test_api_sessions.py

import pytest
from httpx import AsyncClient
from web.app import app


@pytest.fixture
async def client():
async with AsyncClient(app=app, base_url="http://test") as client:
yield client


@pytest.mark.asyncio
async def test_list_sessions_empty(client, tmp_path, monkeypatch):
"""セッションなしの場合、空リストを返す。"""
monkeypatch.setattr("web.routes.api_sessions.OUTPUT_DIR", tmp_path)

response = await client.get("/api/sessions")

assert response.status_code == 200
data = response.json()
assert data["sessions"] == []
assert data["total"] == 0
assert data["pages"] == 0


@pytest.mark.asyncio
async def test_list_sessions_with_filter(client, tmp_path, monkeypatch):
"""タイプフィルタが正しく動作する。"""
# セッションを作成
_create_mock_session(tmp_path, "20260622_idea", type="idea")
_create_mock_session(tmp_path, "20260622_review", type="review")
monkeypatch.setattr("web.routes.api_sessions.OUTPUT_DIR", tmp_path)

response = await client.get("/api/sessions?type=idea")

assert response.status_code == 200
data = response.json()
assert len(data["sessions"]) == 1
assert data["sessions"][0]["type"] == "idea"


@pytest.mark.asyncio
async def test_get_session_not_found(client):
"""存在しないセッションは404を返す。"""
response = await client.get("/api/sessions/nonexistent")
assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_session(client, tmp_path, monkeypatch):
"""セッション削除が正しく動作する。"""
session_dir = tmp_path / "20260622_test"
session_dir.mkdir()
(session_dir / "session_meta.json").write_text('{"type": "idea"}')
monkeypatch.setattr("web.routes.api_sessions.OUTPUT_DIR", tmp_path)

response = await client.delete("/api/sessions/20260622_test")

assert response.status_code == 200
assert not session_dir.exists()
```

### 12.2 SSEストリームテスト

```python
@pytest.mark.asyncio
async def test_idea_stream_emits_events(client, mock_api):
"""SSEストリームが正しいイベントを送信する。"""
request_body = {
"plan": mock_plan_dict,
"prompt": "テスト",
"time_limit": 60,
}

events = []
async with client.stream("POST", "/api/idea/stream", json=request_body) as response:
assert response.status_code == 200
async for line in response.aiter_lines():
if line.startswith("data: "):
event = json.loads(line[6:])
events.append(event)
if event["type"] in ("done", "error"):
break

# 基本的なイベント順序の確認
event_types = [e["type"] for e in events]
assert "round_start" in event_types
assert "utterance" in event_types
assert event_types[-1] in ("done", "error")
```

---

## 13. API ドキュメント (自動生成)

FastAPI の自動ドキュメント機能で以下が利用可能:

| URL | 内容 |
|-----|------|
| `/docs` | Swagger UI (インタラクティブ) |
| `/redoc` | ReDoc (見やすいドキュメント) |
| `/openapi.json` | OpenAPI スキーマ (JSON) |

```python
# 無効化する場合 (本番環境)
app = FastAPI(
docs_url="/docs" if settings.debug else None,
redoc_url="/redoc" if settings.debug else None,
)
