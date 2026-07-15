# 第9章 評価・フィードバックシステム

---

## 9.1 自己評価の設計

各 AI エージェントは議論終了後、自分自身の貢献を振り返り評価します。この自己評価は「メタ認知」を促し、次回以降のパフォーマンス向上に直結します。

### 9.1.1 評価軸（論理的厳密性 / 技術的深度 / 新規性 / 再現可能性）

研究者向けシステムとして、評価軸はビジネス指標ではなく**研究の質に関する指標**を採用します。

| 評価軸 | 定義 | 高スコアの例 |
|---|---|---|
| **論理的厳密性** | 議論に飛躍がなく、根拠に基づいた発言ができたか | 計算量をO記法で明示、定理を引用して正当化 |
| **技術的深度** | 議論を何段深められたか。表層で止まらず本質に到達したか | 「WL-testの限界は実用上問題にならない」と条件付きで判断 |
| **新規性** | 他者が出していない新しい視点・知見を提供できたか | 別分野のアナロジーを持ち込み、新解法を提案 |
| **再現可能性** | 実験・実装に落とせる形で貢献したか | 具体的なデータセット名・パラメータ値・手順を提示 |

**ロール固有の評価軸**:

上記4軸に加えて、各ロールの `evaluation_criteria` に定義された固有軸も使用されます。

```
例: 😈 穴探し の場合
- 穴の発見力
- 反例の具体性
- 修復案の提示
- 致命度の判断
```

最終的な自己評価は **共通4軸 + ロール固有軸** の組み合わせから、ロール固有軸を優先して使用します。（共通4軸はロール固有軸で十分カバーされるため、重複する場合はロール固有軸のみ）

---

### 9.1.2 評価プロンプトの構造

```python
SELF_EVALUATION_PROMPT = """議論が完了しました。自分の貢献を振り返り、評価してください。

【あなたの役割】
{role_display_name} ({role_id})

【あなたに期待されていたこと】
{expected_contribution}

【あなたの評価基準】
{evaluation_criteria_formatted}

【議論のODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【議論ログ（あなたの発言をハイライト）】
{discussion_log_with_highlights}

【出力形式 (JSON)】
{{
"scores": {{
"{criteria_1_name}": <1-5の整数>,
"{criteria_2_name}": <1-5の整数>,
"{criteria_3_name}": <1-5の整数>,
"{criteria_4_name}": <1-5の整数>
}},
"avg_score": <平均値 小数点1桁>,
"reasoning": "<3-5文で振り返り。何ができて何ができなかったか>",
"key_contributions": ["<主な貢献1>", "<主な貢献2>"],
"missed_opportunities": ["<やるべきだったがやらなかったこと>"]
}}

【評価の心がけ】
- 自分に甘くしない。客観的に。
- 5は「完璧にできた」。4は「おおむねできた」。3は「普通」。2は「不十分」。1は「全くできなかった」。
- missed_opportunities は必ず1つ以上挙げること（完璧な議論はない）。"""
```

---

### 9.1.3 スコアリング（1-5）とテキスト振り返り

**スコアの基準**:

| スコア | 意味 | 基準 |
|---|---|---|
| 5 | 卓越 | 期待を大きく超える貢献。議論の転換点を作った |
| 4 | 良好 | 期待通りの貢献。議論を前に進めた |
| 3 | 普通 | 最低限の役割は果たしたが、特筆する貢献なし |
| 2 | 不十分 | 役割を十分に果たせなかった。発言が浅い |
| 1 | 不可 | 役割から大きく逸脱。議論に悪影響を与えた |

**テキスト振り返りの構成**:

```json
{
"scores": {
"穴の発見力": 5,
"反例の具体性": 4,
"修復案の提示": 4,
"致命度の判断": 5
},
"avg_score": 4.5,
"reasoning": "Round 2 で音響検知の前提問題を指摘し、議論の焦点を「音響ならでは」のモードに絞ることに成功した。代替案（エアリーク検知）が最終結論の核となった。ただし Round 3 での修復案が抽象的で、もう少し具体的な実装パスを示すべきだった。",
"key_contributions": [
"音響検知可能な異常モードの限界を指摘し方向転換を促した",
"エアリーク検知という具体的な代替案の提示"
],
"missed_opportunities": [
"修復案として超音波マイクの具体的な製品型番・スペックまで踏み込めた"
]
}
```

---

## 9.2 他者評価の設計

### 9.2.1 各 AI が全他者を評価

自己評価と同時に、参加した全他者に対する評価も行います。これにより**相互チェック**が働き、自己評価の甘さ/厳しさを補正できます。

```python
PEER_EVALUATION_PROMPT = """議論の参加者をそれぞれ評価してください。

【あなた】
{self_role_display_name}

【評価対象】
{other_agents_list}

【議論ログ】
{discussion_log}

【評価基準】
各参加者の「議論への貢献度」を5点満点で評価し、1行コメントを添えてください。

- 5: 議論を決定的に前進させた。この人がいなければ結論が変わった。
- 4: 有用な貢献をした。議論の質を上げた。
- 3: 普通の貢献。可もなく不可もなく。
- 2: 貢献が薄かった。もっとやれたはず。
- 1: 議論を阻害した。

【出力形式 (JSON)】
{{
"{other_role_id_1}": {{
"score": <1-5>,
"comment": "<1行コメント。具体的な貢献/不足を指摘>"
}},
"{other_role_id_2}": {{
"score": <1-5>,
"comment": "<1行コメント>"
}}
}}

【注意】
- 自分自身は評価しない
- 同調圧力に流されず、正直に評価する
- コメントは具体的に（「良かった」ではなく「Round 2のXXの指摘が議論を転換させた」）"""
```

---

### 9.2.2 スコア + 1行コメント

他者評価は自己評価より簡潔に、**スコア（1-5）+ 具体的な1行コメント**で構成します。

**出力例**:

```json
{
"theorist": {
"score": 5,
"comment": "manifold仮定の限界を自分から出し、multi-scale解法を導いた。議論のMVP。"
},
"experimentalist": {
"score": 4,
"comment": "ablation条件の設計がclean。ただしリソース見積もりがやや楽観的。"
},
"implementer": {
"score": 4,
"comment": "FAISS-GPUの提案で計算量問題を即座に解決した。コード片が分かりやすい。"
}
}
```

**コメントの品質要件**:
- 具体的な発言やラウンドを引用すること
- 「良い」「悪い」だけの抽象的コメントは不可
- 改善点を含む場合は建設的な表現にすること

---

## 9.3 指揮者による総合評価

全 AI の自己評価・他者評価を受けた後、指揮者が**総合的な観点から議論全体を評価**します。

### 9.3.1 MVP 選出

```python
ORCHESTRATOR_EVALUATION_PROMPT = """議論全体を評価し、総合フィードバックを生成してください。

【ODSC】
{odsc}

【議論ログ全文】
{full_discussion_log}

【各AIの自己評価】
{self_evaluations_formatted}

【各AIの他者評価】
{peer_evaluations_formatted}

【あなたの評価タスク】

1. MVP選出:
- 議論に最も貢献したAIを1体選ぶ
- 選出理由を具体的に（どの発言がどう議論を動かしたか）

2. ODSC達成度:
- Objective は達成されたか
- Success Criteria はどの程度満たされたか
- 達成/未達成の根拠を具体的に

3. 各AIへの個別フィードバック:
- 良かった点（strengths_noted）: 具体的に2-3個
- 改善すべき点（improvements_noted）: 具体的に1-2個
- 次回への期待（orchestrator_feedback）: 1文で

【出力形式 (JSON)】
{{
"overall_discussion_quality": <1.0-5.0 小数点1桁>,
"mvp": {{
"role_id": "<MVP の role_id>",
"reason": "<選出理由>"
}},
"odsc_achievement": {{
"achieved": true/false,
"detail": "<達成度の説明>"
}},
"per_agent_feedback": {{
"{role_id}": {{
"strengths_noted": ["<良かった点1>", "<良かった点2>"],
"improvements_noted": ["<改善点1>"],
"orchestrator_feedback": "<次回への期待（1文）>"
}}
}}
}}"""
```

**MVP選出の基準**:

| 基準 | 重み | 説明 |
|---|---|---|
| 議論の転換点を作ったか | 高 | 結論を決定的に変えた発言 |
| 他者評価の平均スコア | 中 | 参加者からの客観的評価 |
| ODSC達成への寄与度 | 中 | 目標に直結する貢献 |
| 自己評価とのギャップ | 低 | 謙虚さ/自己認識の正確さ |

---

### 9.3.2 ODSC 達成度判定

```python
@dataclass
class ODSCAchievement:
achieved: bool
detail: str
objective_met: bool
deliverable_met: bool
criteria_met: bool
convergence_final: float
```

**判定の例**:

```json
{
"achieved": true,
"detail": "技術・実験の2軸で具体的な設計指針が得られた。仮説5つが明確に定義され、実験計画もclean。ただし計算リソースの最終見積もりがやや不足。",
"objective_met": true,
"deliverable_met": true,
"criteria_met": true,
"convergence_final": 0.88
}
```

---

### 9.3.3 各 AI への個別フィードバック生成

指揮者は各 AI に対して、次回セッションで参照される具体的なフィードバックを生成します。

**フィードバックの構成**:

```json
{
"theorist": {
"strengths_noted": [
"kNNグラフの理論的根拠をmanifold測地距離近似として明確に定式化した",
"WL-testの限界について実用上の影響度まで踏み込んで議論した"
],
"improvements_noted": [
"multi-scaleのk選択について理論的な最適性の議論が不足。ヒューリスティックで終わった"
],
"orchestrator_feedback": "multi-scaleパラメータの理論的選択基準について、次回はより踏み込んだ議論を期待。"
},
"devil": {
"strengths_noted": [
"密度不均一データでのkNN破綻を具体的に指摘し議論を転換させた",
"自分が提案した解法にも自己批判を入れ知的誠実さを示した"
],
"improvements_noted": [
"Round 4で指摘が減った。最終確認ラウンドでも残リスクを指摘すべきだった"
],
"orchestrator_feedback": "最終ラウンドでも批判力を維持すること。合意形成圧力に負けない。"
}
}
```

---

## 9.4 フィードバックの YAML 蓄積

### 9.4.1 feedback_history への追記

セッション完了後、各ロールの YAML ファイルに評価結果を書き込みます。

```python
class FeedbackManager:
"""評価結果をロール YAML に蓄積・管理"""

def __init__(self, roles_dir: Path, max_history: int = 10):
self.roles_dir = roles_dir
self.max_history = max_history

def update_role_feedback(
self,
role_id: str,
session_id: str,
date: str,
topic: str,
self_eval: dict,
peer_avg: float,
orchestrator_feedback: dict,
):
"""セッション結果をロール YAML に追記"""

role_path = self.roles_dir / f"{role_id}.yaml"
role = yaml.safe_load(role_path.read_text(encoding="utf-8"))

# feedback_history が存在しなければ初期化
if "feedback_history" not in role:
role["feedback_history"] = []

# 新しいエントリを作成
entry = {
"session_id": session_id,
"date": date,
"topic": topic,
"self_score_avg": self_eval["avg_score"],
"peer_score_avg": peer_avg,
"strengths_noted": orchestrator_feedback.get("strengths_noted", []),
"improvements_noted": orchestrator_feedback.get("improvements_noted", []),
"orchestrator_feedback": orchestrator_feedback.get("orchestrator_feedback", ""),
}

# 履歴に追加
role["feedback_history"].append(entry)

# 最大数を超えたら古いものを圧縮
if len(role["feedback_history"]) > self.max_history:
role["feedback_history"] = self._compress_old_entries(
role["feedback_history"]
)

# 統計を再計算
role["feedback_stats"] = self._calculate_stats(role["feedback_history"])

# YAML に書き戻し
role_path.write_text(
yaml.dump(role, allow_unicode=True, default_flow_style=False, sort_keys=False),
encoding="utf-8",
)
```

**書き込み後の YAML 例**:

```yaml
feedback_history:
- session_id: "20260620_143052_idea"
date: "2026-06-20"
topic: "点群GNN特徴量抽出の設計指針"
self_score_avg: 4.25
peer_score_avg: 4.5
strengths_noted:
- "kNNの理論的根拠をmanifold測地距離近似として定式化"
- "WL-testの限界を実用面まで踏み込んで議論"
improvements_noted:
- "multi-scaleのk選択の理論的最適性が不足"
orchestrator_feedback: "multi-scaleパラメータの理論的選択基準について次回はより踏み込んだ議論を期待"

- session_id: "20260625_091200_idea"
date: "2026-06-25"
topic: "[follow-up] 点群GNN — multi-scaleの速度問題"
self_score_avg: 4.5
peer_score_avg: 4.75
strengths_noted:
- "階層的multi-scaleのアイデアを即座に定式化"
- "底層k=10+上位層k=40の分離設計を理論的に正当化"
improvements_noted:
- "計算量見積もりの誤差が大きかった(実測で1.5倍ずれ)"
orchestrator_feedback: "計算量の理論見積もりと実測の乖離を意識して、見積もりに安全マージンをつけること"
```

---

### 9.4.2 feedback_stats の自動再計算

```python
def _calculate_stats(self, history: list[dict]) -> dict:
    """フィードバック履歴から統計を計算"""

    if not history:
        return {}

    # 基本統計
    self_scores = [h["self_score_avg"] for h in history]
    peer_scores = [h["peer_score_avg"] for h in history]

    # トレンド計算（直近3回 vs それ以前）
    trend = self._calculate_trend(peer_scores)

    # 頻出する強み・弱みの抽出
    all_strengths = []
    all_improvements = []
    for h in history:
        all_strengths.extend(h.get("strengths_noted", []))
        all_improvements.extend(h.get("improvements_noted", []))

    top_strength = self._most_common_theme(all_strengths)
    top_weakness = self._most_common_theme(all_improvements)

    # 直近トピック
    recent_topics = [h["topic"] for h in history[-5:]]

    return {
        "total_sessions": len(history),
        "avg_self_score": round(sum(self_scores) / len(self_scores), 2),
        "avg_peer_score": round(sum(peer_scores) / len(peer_scores), 2),
        "trend": trend,
        "top_strength": top_strength,
        "top_weakness": top_weakness,
        "recent_topics": recent_topics,
    }

def _calculate_trend(self, scores: list[float]) -> str:
    """スコア推移からトレンドを判定"""

    if len(scores) < 3:
        return "insufficient_data"

    recent = scores[-3:]     # 直近3回
    earlier = scores[:-3]    # それ以前

    if not earlier:
        return "insufficient_data"

    recent_avg = sum(recent) / len(recent)
    earlier_avg = sum(earlier) / len(earlier)

    diff = recent_avg - earlier_avg

    if diff > 0.3:
        return "improving"
    elif diff < -0.3:
        return "declining"
    else:
        return "stable"

def _most_common_theme(self, items: list[str]) -> str:
    """テキストリストから最頻出テーマを抽出（簡易版）"""

    if not items:
        return ""

    # キーワード頻度で判定（簡易実装）
    # 本格的にはLLMでクラスタリングするが、ここではシンプルに
    # 最後に指摘されたものを返す（最新の課題）
    return items[-1] if items else ""
```

**生成される feedback_stats 例**:

```yaml
feedback_stats:
total_sessions: 8
avg_self_score: 4.15
avg_peer_score: 4.30
trend: "improving"
top_strength: "kNNの理論的根拠をmanifold測地距離近似として定式化"
top_weakness: "計算量の理論見積もりと実測の乖離を意識すること"
recent_topics:
- "点群GNN特徴量抽出の設計指針"
- "[follow-up] 点群GNN — multi-scaleの速度問題"
- "自己教師あり学習で時系列特徴抽出"
- "VAE潜在空間の次元数選択"
- "GAN学習の安定化手法比較"
```

---

### 9.4.3 最大履歴数と古いデータの圧縮

YAML ファイルが肥大化しないよう、履歴数に上限を設けます。

```python
MAX_HISTORY = 10  # 直近10セッション分を詳細保持

def _compress_old_entries(self, history: list[dict]) -> list[dict]:
    """古いエントリを圧縮して最大数に収める"""

    if len(history) <= self.max_history:
        return history

    # 戦略: 直近10件は詳細保持、それ以前は統計に吸収して削除
    keep = history[-self.max_history:]

    # 削除分の情報はfeedback_statsに反映済みなので、単純に切り捨て
    # ただし、特に重要なフィードバック（score 5.0 や 1.0）は保持
    exceptional = [
        h for h in history[:-self.max_history]
        if h.get("self_score_avg", 3) >= 4.8 or h.get("self_score_avg", 3) <= 1.5
    ]

    # 例外的に重要なエントリは先頭に保持（最大2件）
    exceptional = exceptional[-2:]

    return exceptional + keep
```

**圧縮のライフサイクル**:

```
セッション 1-10:  全て詳細保持
セッション 11:    セッション1 が圧縮候補 → stats に吸収して削除
セッション 12:    セッション2 が圧縮候補 → stats に吸収して削除
...
セッション 20:    直近10件 + 例外的に重要な過去2件 = 最大12件
```

---

## 9.5 次回実行時のフィードバック活用

### 9.5.1 システムプロンプトへの自動注入

次回セッションで同じロールが選ばれた際、過去のフィードバックが自動的にシステムプロンプトに注入されます。

```python
class FeedbackManager:
    def generate_feedback_context(self, role_id: str) -> str:
        """次回のシステムプロンプトに注入するフィードバックテキストを生成"""

        role = self.load_role(role_id)
        history = role.get("feedback_history", [])
        stats = role.get("feedback_stats", {})

        if not history:
            return ""

        parts = []

        # トレンド情報
        trend = stats.get("trend", "insufficient_data")
        if trend == "improving":
            parts.append("📈 あなたの評価は改善傾向にあります。この調子を維持してください。")
        elif trend == "declining":
            parts.append("📉 あなたの評価が下降傾向です。以下の改善点を特に意識してください。")

        # 直近3回のフィードバック
        recent = history[-3:]
        improvements_seen = set()
        feedback_seen = set()

        for h in recent:
            for imp in h.get("improvements_noted", []):
                improvements_seen.add(imp)
            fb = h.get("orchestrator_feedback", "")
            if fb:
                feedback_seen.add(fb)

        if improvements_seen:
            parts.append("【過去に指摘された改善点】")
            for imp in list(improvements_seen)[-3:]:  # 最大3つ
                parts.append(f"- {imp}")

        if feedback_seen:
            parts.append("【指揮者からの継続的な期待】")
            for fb in list(feedback_seen)[-2:]:  # 最大2つ
                parts.append(f"- {fb}")

        # 強みのリマインド
        if stats.get("top_strength"):
            parts.append(f"【あなたの強み】{stats['top_strength']} — これを活かしてください。")

        return "\n".join(parts)
```

**生成されるテキスト例**:

```
📈 あなたの評価は改善傾向にあります。この調子を維持してください。

【過去に指摘された改善点】
- multi-scaleのk選択の理論的最適性が不足
- 計算量の理論見積もりと実測の乖離を意識すること
- 代替案の具体性を高めること

【指揮者からの継続的な期待】
- multi-scaleパラメータの理論的選択基準について次回はより踏み込んだ議論を期待
- 計算量見積もりに安全マージンをつけること

【あなたの強み】kNNの理論的根拠をmanifold測地距離近似として定式化 — これを活かしてください。
```

このテキストが system prompt の `{feedback_context}` プレースホルダに挿入されます。

---

### 9.5.2 改善傾向の追跡（improving / stable / declining）

**トレンド判定の仕組み**:

```
直近3回の平均スコア vs それ以前の平均スコア

差が +0.3 以上 → "improving" 📈
差が -0.3 以上 → "declining" 📉
それ以外       → "stable"    ━━
```

**トレンドの活用方法**:

| トレンド | 指揮者の対応 |
|---|---|
| `improving` | そのロールを積極的に選定。フィードバックが機能している証拠 |
| `stable` | 通常通り選定。新しい改善点を探す |
| `declining` | 選定時に慎重になる。改善点を強調して指示に含める |

**指揮者プロンプトでの提示方法**:

```
【各ロールの最近のパフォーマンス】
- 🧮 理論屋: trend=improving (4.15→4.50), 強み「定式化」, 弱み「計算量見積もりの精度」
- 😈 穴探し: trend=stable (4.30→4.35), 強み「反例の具体性」, 弱み「最終ラウンドでの批判力低下」
- 📚 文献屋: trend=declining (4.40→3.90), 弱み「架空論文の引用が2回発生」
  → ⚠️ 信頼性に注意。[要確認]ルールを強調する必要あり。
```

**declining 時の特別対応**:

```python
def should_reinforce_rules(self, role_id: str) -> bool:
    """ルール強化が必要か判定"""
    stats = self.get_stats(role_id)
    return stats.get("trend") == "declining"

def generate_reinforced_instruction(self, role_id: str) -> str:
    """declining時の追加指示を生成"""
    stats = self.get_stats(role_id)
    weakness = stats.get("top_weakness", "")

    return f"""⚠️ 重要: あなたの直近のパフォーマンスが下降傾向です。
特に以下の点を強く意識してください:
- {weakness}
この点が改善されないと、今後の議論で別のロールに交代する可能性があります。"""
```

---

### 評価フロー全体のシーケンス

```
Phase 3 開始
│
├── 1. 各AI に自己評価を依頼（並列実行）
│   ├── theorist.evaluate() → self_eval_theorist
│   ├── devil.evaluate() → self_eval_devil
│   └── experimentalist.evaluate() → self_eval_experimentalist
│
├── 2. 各AI に他者評価を依頼（並列実行）
│   ├── theorist → devil, experimentalist を評価
│   ├── devil → theorist, experimentalist を評価
│   └── experimentalist → theorist, devil を評価
│
├── 3. 指揮者が総合評価を生成
│   ├── MVP 選出
│   ├── ODSC 達成度判定
│   └── 各AI への個別フィードバック
│
├── 4. YAML フィードバック更新
│   ├── theorist.yaml → feedback_history 追記 + stats 再計算
│   ├── devil.yaml → feedback_history 追記 + stats 再計算
│   └── experimentalist.yaml → feedback_history 追記 + stats 再計算
│
└── 5. evaluation.md 出力
```

**API リクエスト数**:

| 処理 | リクエスト数 | モデル |
|---|---|---|
| 自己評価 (3AI) | 3 | 各ロールのモデル |
| 他者評価 (3AI) | 3 | 各ロールのモデル |
| 指揮者総合評価 | 1 | claude-sonnet-4-5 (extended thinking) |
| **合計** | **7** | — |

※ 自己評価と他者評価は1回のAPI呼出で同時に生成可能（プロンプトを統合）。その場合は **3リクエスト + 1 = 4リクエスト** に削減可能。

```python
# 統合版プロンプト（自己評価+他者評価を1回で取得）
COMBINED_EVALUATION_PROMPT = """議論が完了しました。
以下の2つを同時に回答してください。

【Part 1: 自己評価】
{self_eval_instructions}

【Part 2: 他者評価】
{peer_eval_instructions}

【出力形式 (JSON)】
{{
"self_evaluation": {{ ... }},
"peer_evaluations": {{ ... }}
}}"""
```

---

### 9章まとめ: 評価・フィードバック設計の原則

| 原則 | 実現方法 |
|---|---|
| **自律的改善** | 自己評価で自分の弱点を認識し、次回に活かす |
| **相互チェック** | 他者評価で自己評価のバイアスを補正 |
| **具体的指導** | 指揮者フィードバックが「次に何をすべきか」を明確に提示 |
| **蓄積と学習** | YAML に履歴を保存し、セッションを重ねるごとに改善 |
| **トレンド追跡** | improving/stable/declining で長期的な成長を可視化 |
| **コスト効率** | 自己+他者評価を統合プロンプトで1回のAPI呼出に圧縮可能 |

---
