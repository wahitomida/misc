# 第13章 継続議論（--follow-up）設計

---

## 13.1 コンセプトと使用場面

### コンセプト

研究は**1回の議論で完結しない**ものです。アイデアを議論し、実験し、結果を分析し、次の仮説を立てる——このサイクルを AI Orchestra で支援するのが `--follow-up` 機能です。

```
┌─────────────────────────────────────────────────────────────┐
│                     研究のサイクル                             │
│                                                              │
│  Session A (初回)         実験           Session B (follow-up)│
│  ┌──────────────┐       ┌──────┐       ┌──────────────┐     │
│  │アイデア議論   │──────→│ 実験 │──────→│ 結果を踏まえ  │     │
│  │仮説 H1-H5   │       │ 実施 │       │ 再議論       │     │
│  │実験計画     │       │      │       │ H1✅ H3❌    │     │
│  └──────────────┘       └──────┘       │ 新仮説H6,H7  │     │
│                                        └───────┬──────┘     │
│                                                │             │
│                          実験           Session C            │
│                         ┌──────┐       ┌──────────────┐     │
│                         │ 実験 │──────→│ さらに深掘り  │     │
│                         │ 実施 │       │ H6✅ 最終結論 │     │
│                         └──────┘       └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 使用場面

| 場面 | ユーザーの状況 | follow-up の活用 |
|---|---|---|
| 実験結果が出た | 予想と違う結果が出た | 結果を添付して原因分析の再議論 |
| 仮説の検証完了 | H1は確認、H3は棄却 | テーブル更新+次の攻め所を議論 |
| 新情報の発見 | 関連論文を見つけた | 論文情報を追加して方針再検討 |
| 実装上の問題 | 理論通りにいかない | 実装制約を踏まえた代替案議論 |
| 研究の方向転換 | 当初の方針が行き詰まり | 未解決問題をベースに方向転換 |

---

## 13.2 CLI インターフェース

### 13.2.1 基本形（セッション ID 指定）

```bash
# セッションIDを指定して継続
python main.py idea --follow-up 20260620_143052_idea \
"実験したら multi-scale kNN が single k=20 より精度2%上がった。
ただし推論時間が3倍になった。トレードオフをどう解決する？"
```

セッション ID は `output/` ディレクトリ内のフォルダ名です。Tab 補完が効くようにするため、ディレクトリ名をそのまま ID として使用します。

```
output/
├── 20260620_143052_idea/    ← これがセッションID
├── 20260625_091200_idea/
└── 20260625_150000_review/
```

---

### 13.2.2 実験結果ファイルの添付（--attach）

```bash
# CSV の実験結果を添付
python main.py idea --follow-up 20260620_143052_idea \
--attach results/ablation_k.csv \
--attach results/memory_usage.txt \
"添付の実験結果を見て、次の方針を議論して"
```

**添付ファイルの制約**:

| 制約 | 値 | 理由 |
|---|---|---|
| 最大ファイル数 | 5 | コンテキスト爆発防止 |
| 1ファイル最大サイズ | 50KB | token 上限への配慮 |
| 対応形式 | .txt, .csv, .md, .json, .yaml, .py | テキスト系のみ |
| 合計最大文字数 | 10,000文字 | 指揮者への入力サイズ制限 |

**添付ファイルの処理**:

```python
class AttachmentProcessor:
"""添付ファイルの読み込みと前処理"""

MAX_FILES = 5
MAX_FILE_SIZE = 50_000  # 50KB
MAX_TOTAL_CHARS = 10_000
ALLOWED_EXTENSIONS = {".txt", ".csv", ".md", ".json", ".yaml", ".yml", ".py", ".log"}

def process(self, file_paths: list[Path]) -> list[dict]:
"""添付ファイルを処理"""

if len(file_paths) > self.MAX_FILES:
raise TooManyAttachmentsError(f"添付ファイルは最大{self.MAX_FILES}個まで")

attachments = []
total_chars = 0

for path in file_paths:
if not path.exists():
raise FileNotFoundError(f"ファイルが見つかりません: {path}")

if path.suffix not in self.ALLOWED_EXTENSIONS:
raise UnsupportedFileTypeError(f"非対応形式: {path.suffix}")

size = path.stat().st_size
if size > self.MAX_FILE_SIZE:
raise FileTooLargeError(f"ファイルが大きすぎます ({size} bytes): {path}")

content = path.read_text(encoding="utf-8", errors="replace")

# 合計文字数チェック
if total_chars + len(content) > self.MAX_TOTAL_CHARS:
# 超える場合は先頭部分のみ取得
remaining = self.MAX_TOTAL_CHARS - total_chars
content = content[:remaining] + f"\n... (以降省略。全{len(content)}文字中{remaining}文字を掲載)"

total_chars += len(content)

attachments.append({
"name": path.name,
"path": str(path),
"size_bytes": size,
"content": content,
})

return attachments
```

---

### 13.2.3 仮説フォーカス（--focus-hypothesis）

```bash
# 特定の仮説に焦点を当てる
python main.py idea --follow-up 20260620_143052_idea \
--focus-hypothesis H1 H3 \
"H1は確認できた。H3は棄却。次にどこを攻める？"
```

フォーカスされた仮説は指揮者のプロンプトで強調され、議論がその仮説の更新・発展に集中します。

```python
def build_focus_context(self, hypotheses: list[dict], focus_ids: list[str]) -> str:
"""フォーカス仮説のコンテキスト構築"""

parts = ["【フォーカスする仮説】以下の仮説について重点的に議論してください:\n"]

for h in hypotheses:
if h["id"] in focus_ids:
status_emoji = {"unverified": "🔲", "confirmed": "✅", "rejected": "❌"}.get(h["status"], "?")
parts.append(f"  ★ {h['id']}: {h['hypothesis']} [{status_emoji} {h['status']}]")
parts.append(f"    検証方法: {h['verification_method']}")
if h.get("note"):
parts.append(f"    補足: {h['note']}")
parts.append("")

parts.append("上記以外の仮説にも触れてよいが、フォーカス仮説を優先すること。")
return "\n".join(parts)
```

---

## 13.3 前回セッションからの情報引き継ぎ

### 引き継ぎの全体構造

```python
@dataclass
class FollowUpContext:
"""前回セッションから引き継ぐ全情報"""

# 識別情報
parent_session_id: str
chain: list[str]
chain_depth: int

# 前回の成果物
previous_conclusion: str          # report.md の核心
previous_hypotheses: list[dict]   # 仮説テーブル
unresolved_issues: list[str]      # 未解決問題リスト
discussion_summary: str           # 議論の圧縮サマリ（3-5行）

# 前回のメタ情報
previous_agents: list[dict]       # 参加AI情報
previous_feedback: dict           # 評価結果

# 今回の追加情報
new_input: str                    # ユーザーの新しい質問/情報
attached_files: list[dict]        # 添付ファイル
focus_hypotheses: list[str]       # フォーカスする仮説ID
```

---

### 13.3.1 結論

前回の `discussion.json` → `synthesis.final_conclusion` から抽出します。

```python
def _extract_conclusion(self, session_dir: Path) -> str:
"""前回セッションの結論を抽出"""
discussion = json.loads((session_dir / "discussion.json").read_text(encoding="utf-8"))
return discussion["synthesis"]["final_conclusion"]
```

**指揮者プロンプトへの注入**:

```
【前回の結論】
推奨構成: multi-scale kNN (k=10,20,40) + 相対位置PE + EdgeConv 4層
理論根拠: kNNがmanifold測地距離近似として最適、multi-scaleで角・エッジ部も対応
計算量: O(Nk·L) where k=40(max), L=4
```

---

### 13.3.2 仮説テーブル

前回の `report.md` から仮説テーブルを構造化して抽出します。

```python
def _extract_hypotheses(self, report_path: Path) -> list[dict]:
"""report.mdから仮説テーブルを抽出"""

content = report_path.read_text(encoding="utf-8")

# Markdown テーブルのパース
hypotheses = []
in_table = False
for line in content.split("\n"):
if "| ID |" in line or "| H" in line:
in_table = True
if in_table and line.startswith("| H"):
parts = [p.strip() for p in line.split("|")[1:-1]]
if len(parts) >= 4:
hypotheses.append({
"id": parts[0],
"hypothesis": parts[1],
"status": self._parse_status(parts[2]),
"verification_method": parts[3],
})

return hypotheses

def _parse_status(self, status_text: str) -> str:
"""状態テキストをパース"""
if "✅" in status_text or "確認" in status_text:
return "confirmed"
elif "❌" in status_text or "棄却" in status_text:
return "rejected"
elif "🔄" in status_text or "修正" in status_text:
return "modified"
else:
return "unverified"
```

---

### 13.3.3 未解決問題

```python
def _extract_unresolved(self, report_path: Path) -> list[str]:
"""report.mdから未解決問題を抽出"""

content = report_path.read_text(encoding="utf-8")
issues = []

in_section = False
for line in content.split("\n"):
if "未解決問題" in line or "未解決" in line:
in_section = True
continue
if in_section:
if line.startswith("#"):
break  # 次のセクションに到達
if line.strip().startswith(("- ", "1.", "2.", "3.", "4.", "5.")):
issue_text = line.strip().lstrip("- 0123456789.").strip()
if issue_text:
issues.append(issue_text)

return issues
```

---

### 13.3.4 議論要約（圧縮版）

全ラウンドの要約を**さらに3-5行に圧縮**して引き継ぎます。

```python
async def _compress_discussion(self, session_dir: Path) -> str:
"""議論全体を3-5行に圧縮"""

discussion = json.loads((session_dir / "discussion.json").read_text(encoding="utf-8"))

# 各ラウンドの主要結論を抽出
round_conclusions = []
for r in discussion["discussion"]["rounds"]:
convergence = r.get("convergence_check", {}).get("result", {})
reasoning = convergence.get("reasoning", "")
if reasoning:
round_conclusions.append(f"R{r['round']}: {reasoning}")

full_text = "\n".join(round_conclusions)

prompt = f"""以下の議論の流れを3-5行に圧縮してください。
結論と重要な転換点のみ残す。詳細は不要。

{full_text}

圧縮版（3-5行）:"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=200,
)
return response["content"].strip()
```

---

### 13.3.5 参加者と評価

前回の参加者情報と評価結果を引き継ぎ、指揮者が「同じメンバーを継続するか」の判断材料にします。

```python
def _extract_agent_info(self, session_dir: Path) -> tuple[list[dict], dict]:
"""前回の参加者情報と評価を抽出"""

discussion = json.loads((session_dir / "discussion.json").read_text(encoding="utf-8"))

agents = discussion["planning"]["selected_agents"]
feedback = discussion["evaluation"]["orchestrator_feedback"]

return agents, feedback
```

**指揮者への提示形式**:

```
【前回の参加者と評価】
- 🧮 理論屋 (gpt-5.4): 評価4.5/5, MVP。「定式化が的確」
- 😈 穴探し (claude-sonnet-4-5): 評価4.5/5。「前提崩しが秀逸」
- 🔬 実験屋 (gpt-5): 評価4.3/5。「実験設計がclean」

【前回の指揮者フィードバック】
- 🧮: multi-scaleパラメータの理論的選択基準について踏み込み不足
- 😈: 最終ラウンドでの批判力低下
- 🔬: リソース見積もりがやや楽観的
```

---

## 13.4 指揮者の follow-up 計画立案

### 13.4.1 メンバーの継続 / 変更判断

```python
FOLLOW_UP_PLANNING_PROMPT = """これは前回セッションの継続議論です。

【前回のセッション情報】
- セッションID: {parent_session_id}
- 前回の結論: {previous_conclusion}
- 前回の参加者: {previous_agents_summary}
- 前回の評価: {previous_feedback_summary}

【前回の仮説テーブル】
{hypotheses_table}

【前回の未解決問題】
{unresolved_issues}

【前回の議論サマリ】
{discussion_summary}

【今回の新情報/質問】
{new_input}

【添付データ】
{attachments_summary}

【フォーカスする仮説】
{focus_hypotheses}

【あなたの判断事項】

1. メンバー選定:
- 前回と同じメンバーを継続するか？
- 新しいメンバーを追加する必要があるか？
- 外すべきメンバーはいるか？
- 判断理由を明記すること

2. 議論焦点:
- 今回の新情報を踏まえて、何を議論すべきか？
- フォーカス仮説がある場合、それを中心に
- 新たに生まれた問い はあるか？

3. 仮説テーブルの更新方針:
- 確認/棄却すべき仮説はどれか？
- 修正が必要な仮説はあるか？
- 新規仮説を追加すべきか？

4. ODSC:
- 今回の議論の目的、成果物、成功基準

【出力形式】
（Phase 1 と同じ JSON 形式）"""
```

**メンバー変更の判断基準**:

| 判断 | 条件 | 例 |
|---|---|---|
| 継続 | 前回の議論テーマと連続性がある | 前回GNN設計→今回GNN速度改善 |
| 追加 | 新しい観点が必要 | 速度問題発生→🤖実装屋を追加 |
| 交代 | 前回の評価が低い+今回不要 | 📚文献屋が前回貢献薄+今回は実験議論 |
| 全交代 | テーマが大きく変わった | 稀。通常はfollow-upではなく新規セッション |

---

### 13.4.2 議論焦点の決定

指揮者は以下の優先順位で焦点を決定します:

```
1. ユーザーが明示的に質問していること (new_input)
2. --focus-hypothesis で指定された仮説の更新
3. 添付データから読み取れる新発見への対応
4. 前回の未解決問題の解決
5. 前回のフィードバックを踏まえた深掘り
```

---

### 13.4.3 仮説テーブルの更新方針

```python
HYPOTHESIS_UPDATE_PROMPT = """前回の仮説テーブルと今回の新情報を踏まえて、
仮説の状態更新方針を決定してください。

【現在の仮説テーブル】
{current_hypotheses}

【今回の新情報】
{new_input}
{attachments_summary}

【フォーカス仮説】
{focus_hypotheses}

【更新判断の基準】
- confirmed: 実験/データで仮説が支持された
- rejected: 実験/データで仮説が否定された
- modified: 仮説を修正して新しい形にすべき
- unverified: まだ判断材料が不足

【出力形式 (JSON)】
{{
"updates": {{
"H1": {{"new_status": "confirmed", "note": "ablation実験で+2%を確認"}},
"H3": {{"new_status": "rejected", "note": "メモリは3倍増加。効率良くない"}}
}},
"new_hypotheses": [
{{
"id": "H6",
"hypothesis": "階層的multi-scaleは速度1/3で精度維持できる",
"status": "unverified",
"verification_method": "底層k=10 + 上位層k=40 での実験"
}}
],
"reasoning": "H1確認で基本方針は正しい。H3棄却でメモリ戦略の再考が必要。階層化が有望。"
}}"""
```

---

## 13.5 仮説テーブルの状態遷移管理

### 状態遷移図

```
                    ┌──── 実験で確認 ────→ confirmed ✅
                    │
unverified 🔲 ─────┼──── 実験で否定 ────→ rejected ❌
                    │
                    └──── 修正が必要 ────→ modified 🔄
                                               │
                                               ▼
                                          新仮説 H_new 🔲
                                          (元仮説を修正した新版)
```

### 実装

```python
class HypothesisManager:
"""仮説テーブルの管理"""

VALID_TRANSITIONS = {
"unverified": ["confirmed", "rejected", "modified"],
"confirmed": [],         # 確認済みは変更しない
"rejected": ["modified"],  # 棄却からの復活は「修正」のみ
"modified": ["confirmed", "rejected"],  # 修正版は再検証対象
}

def apply_updates(
self,
hypotheses: list[dict],
updates: dict[str, dict],
new_hypotheses: list[dict],
) -> list[dict]:
"""状態更新を適用"""

updated = []
for h in hypotheses:
h_id = h["id"]
if h_id in updates:
new_status = updates[h_id]["new_status"]
# 遷移の妥当性チェック
if new_status in self.VALID_TRANSITIONS.get(h["status"], []):
h["status"] = new_status
h["note"] = updates[h_id].get("note", "")
h["updated_session"] = updates[h_id].get("session_id", "")
else:
# 不正な遷移は無視してログに記録
h["_invalid_transition_attempted"] = new_status
updated.append(h)

# 新規仮説の追加
max_num = self._get_max_num(updated)
for i, new_h in enumerate(new_hypotheses):
if not new_h.get("id"):
new_h["id"] = f"H{max_num + i + 1}"
new_h["status"] = "unverified"
updated.append(new_h)

return updated

def _get_max_num(self, hypotheses: list[dict]) -> int:
"""既存仮説IDの最大番号を取得"""
nums = []
for h in hypotheses:
h_id = h.get("id", "")
if h_id.startswith("H"):
try:
nums.append(int(h_id[1:].replace("'", "").replace("_prime", "")))
except ValueError:
pass
return max(nums) if nums else 0

def generate_table_markdown(self, hypotheses: list[dict]) -> str:
"""Markdownテーブルとして出力"""
status_emoji = {
"unverified": "🔲 未検証",
"confirmed": "✅ 確認済み",
"rejected": "❌ 棄却",
"modified": "🔄 修正",
}

lines = ["| ID | 仮説 | 状態 | 検証方法 | 備考 |"]
lines.append("|---|---|---|---|---|")
for h in hypotheses:
emoji = status_emoji.get(h["status"], "?")
note = h.get("note", "")
lines.append(
f"| {h['id']} | {h['hypothesis']} | {emoji} | {h['verification_method']} | {note} |"
)
return "\n".join(lines)
```

---

## 13.6 セッションチェーンの管理

### 13.6.1 chain_depth と chain 配列

各セッションの `session_meta.json` にチェーン情報を保持します。

```json
{
"session_id": "20260630_100000_idea",
"follow_up": {
"is_follow_up": true,
"parent_session_id": "20260625_091200_idea",
"chain_depth": 2,
"chain": [
"20260620_143052_idea",
"20260625_091200_idea",
"20260630_100000_idea"
],
"trigger": "階層的multi-scaleの実験結果が出た",
"hypotheses_updated": {
"confirmed": ["H3_prime"],
"rejected": [],
"new": ["H8"]
}
}
}
```

**chain_depth の意味**:

| depth | 意味 |
|---|---|
| 0 | 初回セッション（follow-upではない） |
| 1 | 1回目の follow-up |
| 2 | 2回目の follow-up（孫セッション） |
| N | N回目の follow-up |

---

### 13.6.2 history --chain コマンドによる可視化

```bash
$ python main.py history --chain 20260620_143052_idea
```

**出力**:

```
🔗 Session Chain: 点群GNN特徴量抽出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📍 20260620_143052_idea [初回] — 設計指針
   結論: multi-scale kNN + 相対位置PE + EdgeConv
   仮説: H1🔲 H2🔲 H3🔲 H4🔲 H5🔲
   参加: 🧮🔬🤖📚😈
   品質: 4.5/5 | 収束: 0.88

   ↓ (5日後, トリガー: "multi-scale実験結果")

📍 20260625_091200_idea [follow-up #1] — 速度問題
   結論: 階層的multi-scale (底層k=10, 上位k=40)
   仮説: H1✅ H2🔲 H3❌ → H3'🔲 H5🔲 H6🔲
   参加: 🧮🤖😈
   品質: 4.3/5 | 収束: 0.85

   ↓ (5日後, トリガー: "階層的multi-scaleの実装完了")

📍 20260630_100000_idea [follow-up #2] — 最終構成決定
   結論: 階層構造確定。論文用実験計画フィックス。
   仮説: H1✅ H2✅ H3'✅ H5✅ H6🔲 → H8🔲
   参加: 🧮🔬🤖😈📚
   品質: 4.7/5 | 収束: 0.92

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 チェーン統計:
   セッション数: 3
   総所要時間: 14分32秒
   仮説: 8個生成, 5個確認, 1個棄却, 2個未検証
   参加AI延べ: 14体
```

**実装**:

```python
class HistoryViewer:
"""セッション履歴の表示"""

def show_chain(self, session_id: str, output_dir: Path):
"""セッションチェーンを可視化"""

chain = self._build_chain(session_id, output_dir)

console.print(f"\n🔗 Session Chain: {chain[0]['topic']}")
console.print("━" * 50)

for i, session in enumerate(chain):
depth_marker = "📍" if i == 0 else "📍"
follow_type = "[初回]" if i == 0 else f"[follow-up #{i}]"

console.print(f"\n{depth_marker} {session['id']} {follow_type} — {session['short_title']}")
console.print(f"   結論: {session['conclusion_oneliner']}")
console.print(f"   仮説: {self._format_hypotheses_inline(session['hypotheses'])}")
console.print(f"   参加: {''.join(session['agent_emojis'])}")
console.print(f"   品質: {session['quality']}/5 | 収束: {session['convergence']}")

if i < len(chain) - 1:
next_session = chain[i + 1]
days_gap = self._calc_days_gap(session['date'], next_session['date'])
trigger = next_session.get('trigger', '?')
console.print(f"\n   ↓ ({days_gap}日後, トリガー: \"{trigger}\")")

def _build_chain(self, session_id: str, output_dir: Path) -> list[dict]:
"""セッションIDからチェーン全体を構築"""

# まず起点を見つける
meta = self._load_meta(session_id, output_dir)
chain_ids = meta.get("follow_up", {}).get("chain", [session_id])

# チェーン全体のメタデータを収集
chain = []
for sid in chain_ids:
session_meta = self._load_meta(sid, output_dir)
chain.append(self._format_session_summary(session_meta, output_dir / sid))

return chain
```

---

## 13.7 長期的な研究プロジェクトでの活用パターン

### パターン1: 手法開発サイクル

```
Session 1: アルゴリズム設計の議論
  → 仮説5個, 実験計画

(2週間の実験)

Session 2: --follow-up --attach results.csv
  → H1✅ H3❌, 速度問題浮上, 新仮説2個

(1週間の改良実装)

Session 3: --follow-up --attach improved_results.csv
  → 改良版確認, 最終構成決定

Session 4: --follow-up "論文のRelated Workを議論したい"
  → 差別化ポイントの整理, noveltyの言語化
```

### パターン2: 問題解決の深掘り

```
Session 1: "学習が不安定。lossが発散する"
  → 仮説: learning rate? 初期化? データの問題?

Session 2: --follow-up --focus-hypothesis H2
  "初期化をXavier→Heに変えたら少し改善したが完全ではない"
  → H2を修正, 新仮説: gradient clipping + warmup

Session 3: --follow-up --attach training_log.csv
  "warmup入れたら安定した。ただし収束が遅い"
  → 最終対策の確定
```

### パターン3: 論文投稿に向けた段階的整理

```
Session 1: "この研究のcontributionを整理したい"
  → 3つのcontributionを言語化

Session 2: --follow-up "reviewerからこういう指摘が来そう"
  → 想定質問への回答準備

Session 3: --follow-up "実験を追加すべき？何を追加する？"
  → 追加実験計画, rebuttal用データの設計
```

### 推奨プラクティス

| プラクティス | 理由 |
|---|---|
| 1セッションのテーマは1つに絞る | 焦点が散漫にならない |
| 実験結果は必ず --attach で添付 | AI が具体的なデータに基づいて議論できる |
| 2週間以上空いたら --follow-up の要約を確認してから実行 | 文脈の断絶を防ぐ |
| chain_depth が5を超えたら新規セッションを検討 | 引き継ぎ情報が肥大化する |
| 重要な結論が出たらsummary.txtをメモとして保存 | 後から「あのセッションどれだっけ」を防ぐ |

### chain の最大深度と推奨運用

```yaml
# config/settings.yaml
follow_up:
max_chain_depth: 10           # これ以上は新規セッション推奨
warn_chain_depth: 5           # 5で警告表示
context_compression_depth: 3  # 3代以上前のセッションは圧縮サマリのみ引き継ぎ
```

```python
def _check_chain_depth(self, context: FollowUpContext):
"""チェーン深度の警告チェック"""
if context.chain_depth >= self.settings.follow_up.max_chain_depth:
raise ChainTooDeepError(
f"チェーン深度が上限({self.settings.follow_up.max_chain_depth})に達しました。\n"
f"新規セッションを開始することを推奨します。\n"
f"  python main.py idea \"テーマ\"  (--follow-up なしで)"
)

if context.chain_depth >= self.settings.follow_up.warn_chain_depth:
console.print(
f"[yellow]⚠️ チェーン深度: {context.chain_depth}。"
f"引き継ぎ情報が大きくなっています。"
f"テーマが変わった場合は新規セッションの開始を検討してください。[/yellow]"
)
```

---

### 13章まとめ: 継続議論の設計原則

| 原則 | 実現方法 |
|---|---|
| **研究サイクルへの適合** | 議論→実験→再議論のループを自然にサポート |
| **情報の構造化引き継ぎ** | 結論・仮説・未解決問題を構造化して次セッションに渡す |
| **仮説駆動** | 仮説テーブルが研究の進捗を可視化し、次のアクションを明確に |
| **柔軟な入力** | テキスト質問 + ファイル添付 + 仮説フォーカスの組み合わせ |
| **チェーン管理** | 深度追跡と上限設定で引き継ぎの肥大化を防止 |
| **可視化** | history --chain で研究の全体像を一覧表示 |

---
