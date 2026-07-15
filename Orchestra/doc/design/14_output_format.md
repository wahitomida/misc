# 第14章 出力書類フォーマット

---

## 14.1 出力ファイル一覧

1セッションで生成される全ファイルの一覧です。

| # | ファイル名 | 目的 | 対象機能 | 形式 |
|---|---|---|---|---|
| 1 | `session_meta.json` | 検索・一覧用メタデータ | ①② 共通 | JSON |
| 2 | `discussion.json` | 完全ログ（機械処理・再現用） | ①② 共通 | JSON |
| 3 | `full_conversation.md` | 全会話台本（人間が楽しく読む） | ①② 共通 | Markdown |
| 4 | `report.md` | 最終レポート（結論・洞察） | ①② 共通 | Markdown |
| 5 | `evaluation.md` | 評価詳細（自己/他者/指揮者） | ①② 共通 | Markdown |
| 6 | `summary.txt` | 1ページ要約（共有用） | ①② 共通 | プレーンテキスト |
| 7 | `vibe_coding_prompt.md` | AI修正指示書 | ② のみ | Markdown |

---

## 14.2 session_meta.json — セッションメタデータ

過去セッションの検索、一覧表示、follow-up のチェーン構築に使用する軽量ファイルです。

```json
{
"_schema_version": "1.0.0",
"session_id": "20260620_143052_idea",
"type": "idea_discussion",
"status": "completed",
"created_at": "2026-06-20T14:30:52+09:00",
"completed_at": "2026-06-20T14:34:28+09:00",
"duration_sec": 216,
"time_limit_sec": 300,
"user_prompt": "点群データからの特徴量抽出にGNNを適用する際の設計指針",
"user_prompt_preview": "点群データからの特徴量抽出にGNNを適用する際の設計指針",
"expertise": "expert",

"models_used": ["gpt-5.4", "claude-sonnet-4-5", "gpt-4.1"],
"agents_used": ["theorist", "experimentalist", "implementer", "literature", "devil"],
"agent_emojis": ["🧮", "🔬", "🤖", "📚", "😈"],

"total_rounds": 5,
"final_convergence": 0.88,
"total_requests": 35,
"total_tokens": 121500,

"conclusion_oneliner": "multi-scale kNN + 相対位置PE + EdgeConv 4層が推奨構成",

"follow_up": {
"is_follow_up": false,
"parent_session_id": null,
"chain_depth": 0,
"chain": ["20260620_143052_idea"]
},

"hypotheses_summary": {
"total": 5,
"unverified": 5,
"confirmed": 0,
"rejected": 0
},

"evaluation_summary": {
"overall_quality": 4.5,
"mvp": "theorist",
"avg_self_score": 4.33,
"avg_peer_score": 4.50
},

"output_files": {
"discussion_json": "discussion.json",
"full_conversation_md": "full_conversation.md",
"report_md": "report.md",
"evaluation_md": "evaluation.md",
"summary_txt": "summary.txt",
"vibe_coding_prompt_md": null
},

"tags": ["点群", "GNN", "特徴量", "グラフ構築"]
}
```

---

## 14.3 discussion.json — 完全ログ（機械処理用）

全会話の完全な記録を構造化 JSON で保持します。プログラムからの再読込、統計分析、follow-up での参照に使用します。

### 14.3.1 会話 Type A: 指揮者→AI 個別指示

各ラウンド開始前に、指揮者が各 AI に送る非公開の個別指示です。

```json
{
"rounds": [
{
"round": 1,
"private_instructions_sent": {
"theorist": {
"instruction": "点群→グラフ変換の定式化と、GNN層の表現力の理論限界を明示してほしい。特にkNNグラフ vs radius graphの理論的差異について。",
"model": "gpt-4.1",
"level": "minimal",
"tokens_used": {"input": 850, "output": 350},
"duration_sec": 1.8
},
"literature": {
"instruction": "PointNet系との比較軸を整理して。最新SOTAも含めて系譜を示してほしい。",
"model": "gpt-4.1",
"level": "minimal",
"tokens_used": {"input": 900, "output": 280},
"duration_sec": 1.5
}
}
}
]
}
```

---

### 14.3.2 会話 Type B: AI 公開発言

議論の本体。各 AI が公開的に行う発言です。

```json
{
"public_utterances": [
{
"sequence": 1,
"speaker": "theorist",
"speaker_display": "🧮 理論屋",
"type": "discussion",
"content": "まず整理。点群 P={p_i} ∈ R^{N×3} をグラフ G=(V,E) に変換する時点で情報の取捨が起きる。kNNでk=20とすると局所構造は捉えるけどグローバルな幾何は失う。",
"model": "gpt-5.4",
"level": "medium",
"tokens_used": {"input": 2200, "output": 180},
"duration_sec": 8.3,
"reasoning_content": null,
"timestamp": "2026-06-20T14:31:20+09:00"
}
]
}
```

`reasoning_content` は Claude 拡張思考モード使用時のみ値が入ります（通常は `null`）。

---

### 14.3.3 会話 Type C: 指揮者内部判断

指揮者の思考過程・判断メモ。進行管理上の決定を記録します。

```json
{
"orchestrator_memo": "Round 1完了。43秒(予算40秒をやや超過、許容範囲)。理論屋は根拠付きで定式化できた。文献屋も系譜を整理。次のRound 2で穴探し投入。",
"conductor_opening": {
"content": "Round 1開始。テーマ: 問題の定式化。🧮理論屋と📚文献屋、お願いします。",
"model": "gpt-4.1",
"tokens_used": {"input": 600, "output": 80},
"duration_sec": 1.2
}
}
```

---

### 14.3.4 収束判定記録

各ラウンド終了時の収束判定結果を記録します。

```json
{
"convergence_check": {
"prompt_hash": "sha256:abc123...",
"model": "gpt-4.1",
"tokens_used": {"input": 3500, "output": 150},
"duration_sec": 1.8,
"result": {
"score": 0.55,
"reasoning": "kNNグラフの優位性は合意されたが、multi-scaleの具体的設計はまだ",
"remaining_disagreements": ["multi-scaleのk値選定", "PE手法の選択"],
"recommendation": "continue"
}
},
"repetition_check": {
"checked": true,
"is_repeating": false
},
"agreement_check": {
"checked": true,
"excessive_agreement": false
}
}
```

---

### 14.3.5 評価データ

Phase 3 で生成される全評価データを記録します。

```json
{
"evaluation": {
"self_evaluations": {
"theorist": {
"scores": {"定式化の的確さ": 4, "理論的根拠の提示": 5, "計算量の意識": 4, "議論の深化": 4},
"avg_score": 4.25,
"reasoning": "Round 1で定式化、Round 3でmulti-scale正当化ができた。ただしk選択の理論的根拠が不足。",
"key_contributions": ["manifold測地距離近似としてのkNN正当化", "multi-scaleの理論的背景提示"],
"missed_opportunities": ["kの最適選択についてより踏み込んだ議論"]
}
},
"peer_evaluations": {
"theorist": {
"evaluators": {
"devil": {"score": 5, "comment": "manifold仮定の限界を自ら出し、multi-scaleを導いた"},
"experimentalist": {"score": 4, "comment": "定式化は的確。リソース見積もりへの貢献は薄い"}
},
"peer_avg_score": 4.5
}
},
"orchestrator_feedback": {
"overall_discussion_quality": 4.5,
"mvp": {"role_id": "theorist", "reason": "問題の定式化とmulti-scaleの理論的正当化が議論全体を支えた"},
"odsc_achievement": {"achieved": true, "detail": "技術・実験の両軸で設計指針が確定"},
"per_agent_feedback": {
"theorist": {
"strengths_noted": ["manifold測地距離としてのkNN正当化", "WL-testの実用影響の判断"],
"improvements_noted": ["k選択の理論的最適性が不足"],
"orchestrator_feedback": "multi-scaleパラメータの理論的選択基準について次回は踏み込むこと"
}
}
}
}
}
```

---

## 14.4 full_conversation.md — 完全会話台本

**舞台裏も表舞台も指揮者のメモも全て可視化**した、読み物として面白いファイルです。

### 14.4.1 表記ルール（🟦🟩⬜🟨）

| 表記 | 意味 | 含む情報 |
|---|---|---|
| `🟦` コードブロック | 指揮者の内部思考・判断 | 計画の意図、時間調整、メモ |
| `🎼→💡` 太字行 | 指揮者→AI への個別指示 | 期待する貢献、注意点 |
| 通常テキスト **名前**: | AI の公開発言 | 議論の本体 |
| `🎼 [収束: 0.55]` コードブロック | 収束判定・進行判断 | スコア、判断理由 |

---

### 14.4.2 舞台裏の表示方法

```markdown
## 🎼 舞台裏: 計画フェーズ

```
🎼 [内心] テーマは点群×GNN。グラフ構築・PE・表現力の3軸が論点になるはず。
🎼 [内心] 🧮と📚で理論固めて、😈で穴見つけて、🤖でフィージビリティ確認。
🎼 [内心] 5ラウンド、190秒の計画。time_limit=300秒内に収まる。
```

**🎼→🧮** 点群→グラフ変換の定式化と表現力の限界を議論して。kNN vs radiusの理論差異に注目。
**🎼→📚** PointNet系の系譜整理して。最新SOTAの数値も出して。
**🎼→😈** Round 2で登場。前提を崩してくれ。後半まで手を抜くなよ。
```

---

### 14.4.3 コンパクト会話スタイルの設計

各発言は**50〜150文字**で、研究者の会話テンポを再現します。

```markdown
## 💬 Round 1: 問題の定式化

**🧮** まず整理。点群P∈R^{N×3}をグラフG=(V,E)に変換する時点で情報の取捨が起きる。kNNでk=20だと局所は捉えるけどグローバルは失う。ここが最初の分岐点。

**📚** PointNet(Qi+2017)は点ごとMLP+max poolで置換不変性を保証。DGCNN(Wang+2019)がkNNグラフ+EdgeConvで局所構造を入れた。最近だとPTv3(Wu+2024)がattentionで100万点スケール。

**🧮** PTv3はGNNとは少し違う路線だね。Message Passing GNNだとWL-testの限界がある。同型グラフを区別できないケースが理論上存在する。

**😈** そもそもkNNグラフ構築って、密度不均一だったらどうなる？疎な領域でkNN取ると遠い点が繋がって意味ないエッジができるよね。

**🤖** 計算量も気になる。N=10万点でkNN計算するとnaiveにO(N²)。KD-Tree使えばO(N log N)だけどGPU上でのKD-Treeは実装面倒。

```
🎼 [収束: 0.35] 問題空間の整理は進んだが方向性の合意はまだ。予定通り続行。
🎼 [内心] 良い立ち上がり。😈の密度不均一指摘が早くも出た。Round 2で深掘る。
```
```

---

## 14.5 report.md — 最終レポート

### 14.5.1 機能①用（研究向け構成）

```markdown
# 🔬 AI Orchestra 技術検討レポート

> **Session**: 20260620_143052_idea
> **テーマ**: 点群データからの特徴量抽出にGNNを適用する際の設計指針
> **所要時間**: 3分36秒 | **参加AI**: 5体 | **収束度**: 0.88

---

## 1. 問題設定
（入力/出力の数学的定義、求められる性質）

## 2. 技術的洞察（議論から得られた知見）
（洞察①②③...番号付き、条件付きで）

## 3. 提案手法の骨格
（アルゴリズムフロー、計算量）

## 4. 仮説テーブル
（ID / 仮説 / 状態 / 検証方法）

## 5. 実験計画
（条件、ベースライン、データ、指標、リソース、再現性チェックリスト）

## 6. 未解決問題
（番号付き、次のアクション付き）

## 7. 参考文献
（[要確認]タグ付き注意書き含む）

---
*AI Orchestra v1.0 | Research Mode | {date}*
```

---

### 14.5.2 機能②用（課題一覧+修正方針）

```markdown
# 🔬 コードレビュー レポート

> **Session**: 20260625_150000_review
> **対象**: ./src/ (点群GNN特徴抽出)
> **Focus**: pre_submission
> **時間**: 6分18秒 | **パートリーダー**: 6体

---

## 概要
（観点別の課題数テーブル: Critical/Warning/Suggestion）

## 修正方針（全体会議の結論）
（Phase A/B/C の分類と順序）

## 🔴 Critical 課題
（各課題: ファイル, 行, 現状コード, 問題, 修正案, 副作用）

## 🟡 Warning 課題
（同上フォーマット）

## 🟢 Suggestion
（同上フォーマット、簡潔に）

## 📊 議論統計

---
*AI Orchestra v1.0 | Code Review Mode | {date}*
```

---

## 14.6 evaluation.md — 評価詳細

```markdown
# 📊 AI 評価レポート

> **Session**: 20260620_143052_idea

---

## 🏆 総合スコアランキング

| 順位 | AI | 自己評価 | 他者評価 | 総合 |
|---|---|---|---|---|
| 🥇 | 🧮 理論屋 | 4.25 | 4.50 | **4.38** |
| 🥈 | 😈 穴探し | 4.50 | 4.50 | **4.50** |
| 🥉 | 🔬 実験屋 | 4.00 | 4.25 | **4.13** |

---

## 📝 個別評価詳細

### 🧮 理論屋 (gpt-5.4)

#### 自己評価
| 基準 | スコア |
|---|---|
| 定式化の的確さ | ⭐⭐⭐⭐☆ (4/5) |
| 理論的根拠の提示 | ⭐⭐⭐⭐⭐ (5/5) |
| 計算量の意識 | ⭐⭐⭐⭐☆ (4/5) |
| 議論の深化 | ⭐⭐⭐⭐☆ (4/5) |
| **平均** | **4.25** |

**自己振り返り:**
> （reasoning テキスト）

**主な貢献:** （箇条書き）
**やり残し:** （箇条書き）

#### 他者からの評価
| 評価者 | スコア | コメント |
|---|---|---|
| 😈 穴探し | 5/5 | （具体的コメント） |
| 🔬 実験屋 | 4/5 | （具体的コメント） |

#### 🎵 指揮者からのフィードバック
> （orchestrator_feedback テキスト）

---

（各AI分続く）

---

## 📈 議論品質の指標

| 指標 | 値 | 判定 |
|---|---|---|
| ODSC 達成度 | 技術✅ 実験✅ | 達成 |
| 議論の多様性 | 5視点全てが活発 | ✅ |
| 建設的対立 | 批判→修復の流れ成立 | ✅ |
| 収束効率 | 5Rで0.88達成 | ✅ |
| 時間活用率 | 72% | ✅ 適正 |

---

## 📝 YAML フィードバック更新内容

（各ロールのYAMLに書き込まれた内容のサマリ）

---
*AI Orchestra v1.0 | {date}*
```

---

## 14.7 summary.txt — 1ページ要約

Slack、メール、チャットにそのまま貼り付けられる**プレーンテキスト**形式です。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔬 AI Orchestra 結果サマリ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

日時: 2026-06-20 14:30-14:34 (3分36秒)
テーマ: 点群データからのGNN特徴量抽出の設計指針
参加AI: 🧮理論(gpt-5.4) / 😈穴探(claude-s4-5) / 🔬実験(gpt-5) / 📚文献(gpt-5.4) / 🤖実装(claude-s4-5)

━━ 結論 ━━

推奨構成: multi-scale kNN (k=10,20,40) + 相対位置PE + EdgeConv 4層
計算量: O(Nk·L), N=10万でも実用的

━━ 主要洞察 ━━

1. kNNがmanifold測地距離近似として理論的に最適
2. 密度不均一にはmulti-scaleで対応（角・エッジ部も）
3. WL-test限界は実用上問題なし（PE追加で十分）
4. spectral PEはオフラインのみ、リアルタイムは相対位置PE

━━ 仮説 (5個) ━━

H1🔲 multi-scale > single k (ScanObjectNNで検証)
H2🔲 相対位置PE ≈ spectral PE (ModelNet40 ablation)
H3🔲 GNN < Transformer in memory (N>5万)
H4🔲 k±5で精度変化<0.5% (感度分析)
H5🔲 multi-scaleが角・エッジ部で効く (CADデータ)

━━ 次のアクション ━━

1. 36条件×3seed×3データセットの実験実行 (A100×4, 約10日)
2. ベースライン: PointNet++, PTv3, DGCNN
3. 評価: OA, mAcc, latency, GPU memory

━━ 統計 ━━

収束: 0.88 | 品質: 4.5/5 | MVP: 🧮理論屋
詳細: output/20260620_143052_idea/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 14.8 vibe_coding_prompt.md — AI 修正指示書

機能②のみで生成。コーディング AI にそのまま渡して修正作業を開始させるためのファイルです。

### 14.8.1 プロンプトとしての最適構成

```markdown
# 🤖 コード修正指示書（AI向け）

> このファイルはバイブコーディング用のプロンプトです。
> そのままコーディングAIに渡してください。

---

## プロジェクトコンテキスト

### 概要
このプロジェクトは「点群からのGNN特徴抽出」の研究実装です。
PyTorch + PyTorch Geometricで実装されています。

### ディレクトリ構成
```
src/
├── feature_extraction/
│   ├── __init__.py
│   ├── pipeline.py           ← [Task 1, Task 3]
│   ├── multi_scale_knn.py    ← [Task 2]
│   └── models/
│       └── edge_conv.py      ← [Task 4]
├── training/
│   ├── train.py              ← [Task 5]
│   └── loss.py               ← [Task 6]
└── utils/
    └── data_loader.py        ← [Task 7]
```

### 技術スタック
- Python 3.11 / PyTorch 2.x / PyG 2.5+ / FAISS-GPU

---

## 修正タスク一覧（優先度順）

### 🔴 Task 1: [Critical] multi_scale_knn.py L38 — 正規化漏れ

**論文の式(3):**
h_i = σ(Σ_{j∈N(i)} (h_j - h_i) / |N(i)| · W)

**現状のコード:**
```python
msg = self.mlp(x[edge_index[0]] - x[edge_index[1]])
out = scatter_add(msg, edge_index[1], dim=0)
```

**問題:** `scatter_add` を使っているが、論文では近傍数 |N(i)| で正規化している。

**修正:**
```python
out = scatter_mean(msg, edge_index[1], dim=0)  # scatter_add → scatter_mean
```

**影響:** 学習済みモデルは再学習が必要。

---

### 🔴 Task 2: [Critical] loss.py L15 — log(0)

**現状:**
```python
loss = -torch.log(pred[target == 1]).mean()
```

**修正:**
```python
loss = -torch.log(pred[target == 1].clamp(min=1e-7)).mean()
```

---

（以降タスク3-7が続く）
```

---

### 14.8.2 グローバル制約の設計

修正指示書の末尾に、全タスク共通のルールをまとめます。

```markdown
## グローバル制約（全タスク共通）

### コーディング規約
1. **docstring**: Google Style
2. **型ヒント**: 全 public メソッドに付与
3. **命名**: snake_case 統一。略語禁止
4. **import**: `from __future__ import annotations` を各ファイル先頭に
5. **ログ**: `logging` モジュール使用（print 禁止）
6. **定数**: マジックナンバー禁止。モジュール定数として定義

### 技術制約
7. **Python**: 3.11 互換
8. **テスト**: `pytest tests/` がパスすること
9. **依存**: 新規パッケージ追加時は requirements.txt 追記
10. **性能**: 既存ベンチマーク（100画像/秒）を下回らない

### 出力形式
11. **修正後はファイル全体を出力**（差分ではなく）
12. 修正箇所に**インラインコメント**で理由記載
13. Task間に依存がある場合は**番号順に修正**

### 禁止事項
14. テスト未確認での API 変更
15. 後方互換性を壊す変更（deprecation 期間を設ける）
16. `# TODO` の放置（修正するか削除）
```

---

### 14.8.3 タスク間依存関係の明示

```markdown
## タスク間の依存関係

```
Task 1 (正規化漏れ)
└── Task 3 (精度確認) ← Task 1 の修正後に実行
    
Task 5 (train.py分割)
├── Task 6 (loss.py 修正) ← 分割後に修正
└── Task 7 (DataLoader最適化) ← 分割後に修正

Task 2 (log(0)) ← 独立。いつ修正してもOK
Task 4 (EdgeConv改良) ← 独立。いつ修正してもOK
```

**修正順序:**
1. Task 2 (独立、即修正可)
2. Task 1 → Task 3 (正規化→確認)
3. Task 4 (独立)
4. Task 5 → Task 6 → Task 7 (構造→ロジック→性能)
```

---

## 14.9 出力ディレクトリ構成

### 機能① の出力

```
output/
└── 20260620_143052_idea/
    ├── session_meta.json          # 2KB  検索・一覧用
    ├── discussion.json            # 50-200KB  完全ログ
    ├── full_conversation.md       # 5-20KB  会話台本
    ├── report.md                  # 3-10KB  最終レポート
    ├── evaluation.md              # 2-5KB  評価詳細
    └── summary.txt                # 1-2KB  1ページ要約
```

### 機能② の出力

```
output/
└── 20260625_150000_review/
    ├── session_meta.json
    ├── discussion.json
    ├── full_conversation.md
    ├── report.md
    ├── evaluation.md
    ├── summary.txt
    └── vibe_coding_prompt.md      # 5-15KB  AI修正指示書 (②のみ)
```

### follow-up チェーンの出力

```
output/
├── 20260620_143052_idea/          # 初回
├── 20260625_091200_idea/          # follow-up #1
└── 20260630_100000_idea/          # follow-up #2
```

各セッションは独立したディレクトリとして保存され、`session_meta.json` の `follow_up.chain` でリンクされます。

### ディレクトリ名のフォーマット

```
{YYYYMMDD}_{HHMMSS}_{type}

- YYYYMMDD: 日付
- HHMMSS: 時刻
- type: "idea" または "review"
```

### .gitignore 推奨

```gitignore
# AI Orchestra 出力（リポジトリに含めない場合）
output/

# ただし session_meta.json だけは含めてもよい
# !output/*/session_meta.json
```

---

### 14章まとめ: 出力フォーマットの設計原則

| 原則 | 実現方法 |
|---|---|
| **用途別分離** | JSON（機械処理）/ Markdown（人間閲読）/ txt（共有）を分離 |
| **完全性** | discussion.json に全会話 Type A/B/C を漏れなく記録 |
| **可読性** | full_conversation.md で舞台裏も含めた会話劇として楽しめる |
| **実用性** | summary.txt はそのままSlackに貼れる。vibe_coding_prompt.md はAIに渡せる |
| **検索性** | session_meta.json で軽量な一覧・検索が可能 |
| **連携性** | follow-up チェーンで複数セッションを横断的に参照 |

---
