# 第2章 KotoBuddy API 連携仕様

---

## 2.1 エンドポイントと認証方式

AI Orchestra は社内提供の KotoBuddy API を通じて複数の LLM にアクセスします。KotoBuddy は Azure OpenAI Service と Amazon Bedrock を統合したエンドポイントであり、2つの接続モードが存在します。

### 2.1.1 openai モード

KotoBuddy 統合エンドポイント（litellm ベース）を使用するモードです。**AI Orchestra のデフォルトモード**であり、1つのエンドポイントから全モデル（Azure OpenAI + Bedrock）にアクセスできます。

| 項目 | 値 |
|---|---|
| エンドポイント例 | `https://api.rdbuddy.rdinx.rd.omron.com/v1` |
| 認証ヘッダ | `Authorization: Bearer <api-key>` |
| リクエストパス | `<endpoint>/chat/completions` |
| SDK | OpenAI Python SDK v1 系（`from openai import OpenAI`） |

```python
from openai import OpenAI

client = OpenAI(
api_key=os.environ["KOTOBUDDY_API_KEY"],
base_url=os.environ["KOTOBUDDY_ENDPOINT"],  # https://.../v1
)

response = client.chat.completions.create(
model="gpt-5.4",
messages=[{"role": "user", "content": "Hello"}],
)
```

**特徴**:
- 全19モデル（うち15が利用可能）に単一エンドポイントでアクセス
- モデル名をそのまま `model` パラメータに指定
- GPT-5 系で `reasoning_effort` を使う場合は `extra_body` が必要（後述）

---

### 2.1.2 azure モード

Azure API Management (APIM) を直接パススルーするモードです。Azure OpenAI の REST API 仕様に準拠します。

| 項目 | 値 |
|---|---|
| エンドポイント例 | `https://api-buddypjjidai.azure-api.net/openai/direct` |
| 認証ヘッダ | `api-key: <api-key>` (**Bearer ではない**) |
| リクエストパス | `<endpoint>/openai/deployments/<deployment>/chat/completions?api-version=2024-12-01-preview` |
| 必須環境変数 | `API_VERSION` (例: `2024-12-01-preview`) |

```python
from openai import AzureOpenAI

client = AzureOpenAI(
api_key=os.environ["KOTOBUDDY_API_KEY"],
azure_endpoint=os.environ["KOTOBUDDY_ENDPOINT"],
api_version=os.environ["API_VERSION"],
)

response = client.chat.completions.create(
model="gpt-5",  # = Azure deployment 名
messages=[{"role": "user", "content": "Hello"}],
)
```

**特徴**:
- Azure 上の deployment 名がそのままモデル名になる
- 利用可能モデルは配布元の deployment 設定に依存
- `extra_body={"allowed_openai_params": [...]}` を送ると **逆に 400 エラーになる**
- 実機検証では `gpt-5` のみ動作確認済み

---

### 2.1.3 モード自動判定ロジック

AI Orchestra の API クライアントは、エンドポイント URL からモードを自動判定します。

```python
def detect_mode(endpoint: str, explicit_mode: str | None = None) -> str:
"""エンドポイントURLからモードを自動判定"""

# 環境変数 KOTOBUDDY_MODE で明示指定されている場合はそちらを優先
if explicit_mode:
return explicit_mode  # "openai" or "azure"

# URL パターンで判定
if "/openai/direct" in endpoint or "azure-api.net" in endpoint:
return "azure"
else:
return "openai"
```

**判定ルール**:

| URL に含まれる文字列 | 判定結果 |
|---|---|
| `/openai/direct` | azure モード |
| `azure-api.net` | azure モード |
| それ以外 | openai モード |

**環境変数 `KOTOBUDDY_MODE`** で明示指定することも可能（`"openai"` or `"azure"`）。

**モード別の動作差異まとめ**:

| 動作 | openai モード | azure モード |
|---|---|---|
| 認証ヘッダ | `Authorization: Bearer <key>` | `api-key: <key>` |
| モデル指定 | `model` パラメータ | deployment 名 |
| `extra_body.allowed_openai_params` | GPT-5系で**必要** | **送ると400エラー** |
| 利用可能モデル | 全15モデル | deployment に依存 |
| Claude 系 | ✅ 利用可能 | ❌ 不可 |

---

## 2.2 利用可能モデル一覧と特性

### 2.2.1 Azure OpenAI モデル（GPT-4.1 / GPT-5 系 / o 系）

| モデル | 入力 token | 出力 token | 状態 | 備考 |
|---|---|---|---|---|
| `gpt-4.1-mini` | 128,000 | 32,768 | ✅ 利用可能 | 高速・安価・安定 |
| `gpt-4.1` | 128,000 | 32,768 | ✅ 利用可能 | temperature/max_tokens 制御可 |
| `gpt-5-mini` | 400,000 | 128,000 | ✅ 利用可能 | reasoning_effort 対応 |
| `gpt-5` | 400,000 | 128,000 | ✅ 利用可能 | reasoning_effort 対応 |
| `gpt-5.1` | 400,000 | 128,000 | ✅ 利用可能 | reasoning_effort 対応 |
| `gpt-5.2` | 400,000 | 128,000 | ✅ 利用可能 | reasoning_effort 対応 |
| `gpt-5.4` | 1,000,000 | 128,000 | ✅ 利用可能 | reasoning_effort 対応 / 入力1M token |
| `o1` | 200,000 | 100,000 | ✅ 利用可能 | 推論モデル |
| `o3-mini` | 200,000 | 100,000 | ✅ 利用可能 | 推論モデル |
| `o4-mini` | 200,000 | 100,000 | ✅ 利用可能 | 推論モデル |
| `gpt-4o-mini` | 128,000 | 16,384 | ⚠️ 廃止予定 | **2026/9/30 廃止** |
| `gpt-4o` | 128,000 | 16,384 | ⚠️ 廃止予定 | **2026/9/30 廃止** |

**AI Orchestra でのモデル使い分け**:

| 用途 | 推奨モデル | 理由 |
|---|---|---|
| 指揮者（計画立案） | `gpt-5.4` | 1M token入力で全コンテキストを一度に処理可能 |
| 進行管理 | `gpt-4.1` | 高速・安定・temperature制御可 |
| 深い推論が必要なエージェント | `gpt-5.4` (high) | reasoning_effort=high で深い思考 |
| 高速応答エージェント | `gpt-5-mini` (low) | 速度重視の発言 |
| 推論系タスク | `o4-mini` | 推論特化モデル |

---

### 2.2.2 Amazon Bedrock モデル（Claude 系）

| モデル | 入力 token | 出力 token | 状態 | 備考 |
|---|---|---|---|---|
| `claude-sonnet-4` | 200,000 | 64,000 | ✅ 利用可能 | 拡張思考対応 |
| `claude-sonnet-4-5` | 200,000 | 64,000 | ✅ 利用可能 | 拡張思考対応（現行推奨） |
| `claude-opus-4-1` | 200,000 | 32,000 | ✅ 利用可能 | 高品質 |
| `claude-3-haiku` | 200,000 | 4,096 | ❌ 利用不可 | Bedrock側 Legacy 扱い |
| `claude-3-5-sonnet` | 200,000 | 8,192 | ❌ 利用不可 | Bedrock側 End-of-Life |
| `claude-3-7-sonnet` | 200,000 | 64,000 | ❌ 利用不可 | Bedrock側 End-of-Life |
| `claude-opus-4` | 200,000 | 32,000 | ❌ 利用不可 | Bedrock側 End-of-Life |

**利用不可モデルのエラー**: litellm が `404 NotFoundError: BedrockException` を返します。

**AI Orchestra でのモデル使い分け**:

| 用途 | 推奨モデル | 理由 |
|---|---|---|
| 最終統合・要約 | `claude-sonnet-4-5` | 拡張思考で丁寧にまとめる |
| 穴探し・批判的分析 | `claude-sonnet-4-5` | 思考プロセスが可視化され、論理的 |
| 実装観点の分析 | `claude-sonnet-4` | 拡張思考+コード理解力 |
| 深い技術分析 | `claude-opus-4-1` | 最高品質（拡張思考非対応） |

---

### 2.2.3 各モデルのパラメータ制約

モデルによって指定可能なパラメータが異なります。AI Orchestra はモデル種別に応じてパラメータを自動切替します。

| モデル群 | temperature | max_tokens | reasoning_effort | verbosity | 拡張思考 |
|---|---|---|---|---|---|
| gpt-4.1 / gpt-4.1-mini | ✅ (0〜1) | ✅ | ❌ | ❌ | ❌ |
| gpt-5 / gpt-5-mini / gpt-5.1 / gpt-5.2 / gpt-5.4 | ❌ **指定不可** | ❌ **指定不可** | ✅ | ✅ | ❌ |
| o1 / o3-mini / o4-mini | ❌ 避けるのが安全 | ❌ 避けるのが安全 | △ 未検証 | ❌ | ❌ |
| claude-sonnet-4 / claude-sonnet-4-5 | ✅ | ✅ | ❌ | ❌ | ✅ |
| claude-opus-4-1 | ✅ | ✅ | ❌ | ❌ | ❌ |
| gpt-4o / gpt-4o-mini (廃止予定) | ✅ | ✅ | ❌ | ❌ | ❌ |

**重要**: GPT-5 系に `temperature` や `max_tokens` を渡すとエラーになります。SDK レベルではエラーにならないことがあるため、AI Orchestra 側で事前にガードします。

```python
def build_params(model: str, level: str, **kwargs) -> dict:
"""モデル種別に応じてパラメータを構築"""
params = {"model": model, "messages": kwargs["messages"]}

if is_gpt5_series(model):
# temperature, max_tokens は指定不可
if level != "none":
params["reasoning_effort"] = level
params["extra_body"] = {"allowed_openai_params": ["reasoning_effort"]}
elif is_claude_thinking_model(model) and level != "none":
# 拡張思考モード
params["extra_body"] = {
"thinking": {"type": "enabled", "budget_tokens": BUDGET_MAP[level]}
}
elif is_standard_model(model):
# temperature, max_tokens 使用可能
params["temperature"] = kwargs.get("temperature", 0.7)
if "max_tokens" in kwargs:
params["max_tokens"] = kwargs["max_tokens"]

return params
```

---

## 2.3 GPT-5 系の reasoning_effort / verbosity 制御

GPT-5 / GPT-5-mini および 5.1 / 5.2 / 5.4 系モデルでは、従来の `temperature` / `max_tokens` の代わりに以下のパラメータで出力を制御します。

### reasoning_effort

モデルが回答生成にどれだけ「考える」かを制御します。

| 値 | 用途 | 速度 | 品質 | AI Orchestra での使用場面 |
|---|---|---|---|---|
| `minimal` | 迅速応答 | 最速 (~3秒) | 最低 | 進行管理の定型指示、収束判定 |
| `low` | 一般的な質問 | 速 (~5秒) | 低 | 最終確認ラウンド、短い応答 |
| `medium` | バランス（既定） | 中 (~10秒) | 中 | 通常の議論発言 |
| `high` | 複雑な分析 | 遅 (~20秒) | 高 | 計画立案、深い技術分析 |

### verbosity

回答の長さ・詳細度を制御します。

| 値 | 応答長 | 内容 |
|---|---|---|
| `low` | 短い | 要点のみ |
| `medium` | 中（既定） | バランス |
| `high` | 長い | 背景説明・補足含む |

### 実装上の注意: `extra_body` の必要性

openai モードで `reasoning_effort` を使用する場合、`extra_body` で `allowed_openai_params` を明示的に許可する必要があります。これを省略すると API 側で拒否されるケースがあります。

```python
client.chat.completions.create(
model="gpt-5.4",
messages=[{"role": "user", "content": "..."}],
reasoning_effort="high",
verbosity="medium",
extra_body={"allowed_openai_params": ["reasoning_effort"]},
)
```

**注意**: azure モード（`/openai/direct`）では逆にこの `extra_body` を送ると **400 エラー**になります。AI Orchestra はモードに応じてこの分岐を自動処理します。

### AI Orchestra の level マッピング

CLI の `level` 引数は、モデル種別に応じて以下のように内部変換されます。

| CLI level | GPT-5 系 | Claude 拡張思考 | o シリーズ | 標準モデル |
|---|---|---|---|---|
| `minimal` | reasoning_effort=minimal | thinking 無効 | (送信なし) | 無視 |
| `low` | reasoning_effort=low | budget_tokens=4,000 | reasoning_effort=low * | 無視 |
| `medium` | reasoning_effort=medium | budget_tokens=8,000 | reasoning_effort=medium * | 無視 |
| `high` | reasoning_effort=high | budget_tokens=16,000 | reasoning_effort=high * | 無視 |
| `none` | パラメータ送信なし | thinking 無効 | 送信なし | 無視 |

\* o シリーズの reasoning_effort は未検証。失敗する場合は `none` にフォールバック。

---

## 2.4 Claude 拡張思考モード（Extended Thinking）

対応モデル: `claude-sonnet-4`, `claude-sonnet-4-5`

（`claude-3-7-sonnet`, `claude-opus-4` も対応モデルだが Bedrock 側で EOL のため利用不可）

### 拡張思考の仕組み

通常の Claude 応答とは別に、「思考プロセス」（reasoning_content）が出力されます。AI Orchestra では最終統合フェーズ（Phase 3）でこの機能を活用し、深い分析を行います。

### 実装方法

```python
response = client.chat.completions.create(
model="claude-sonnet-4-5",
messages=[{"role": "user", "content": "..."}],
extra_body={
"thinking": {
"type": "enabled",
"budget_tokens": 16000,  # 思考に使えるtoken数の上限
}
},
stream=True,  # ストリーム推奨（思考過程を逐次取得）
)
```

### ストリーム応答の構造

ストリームのチャンクには2種類のコンテンツが含まれます:

| フィールド | 内容 |
|---|---|
| `chunk.choices[0].delta.reasoning_content` | 思考プロセス（内部推論） |
| `chunk.choices[0].delta.content` | 本文（最終回答） |

```python
reasoning_parts = []
content_parts = []

for chunk in response:
delta = chunk.choices[0].delta
if delta.reasoning_content:
reasoning_parts.append(delta.reasoning_content)
if delta.content:
content_parts.append(delta.content)

thinking = "".join(reasoning_parts)  # 思考ログ（デバッグ/分析用に保存）
answer = "".join(content_parts)       # 実際の回答
```

### budget_tokens の設計

AI Orchestra では level に応じて budget_tokens を調整します:

| level | budget_tokens | 用途 |
|---|---|---|
| `low` | 4,000 | 簡単な分析 |
| `medium` | 8,000 | 通常の議論発言 |
| `high` | 16,000 | 最終統合・深い分析 |
| `minimal` / `none` | — | 拡張思考無効（通常応答） |

**注意**: 拡張思考を有効にすると応答時間が長くなります（budget_tokens=16000 で 15〜25秒程度）。時間管理においてこのオーバーヘッドを考慮する必要があります。

---

## 2.5 日次リクエスト上限と対策

### 制限仕様

| 項目 | 値 |
|---|---|
| API キー数 | 1ユーザーあたり最大2個 |
| 日次リクエスト上限 | **10,000 req/key** |
| リセットタイミング | 毎日 0:00 |
| 超過時レスポンス | HTTP 401 |

### AI Orchestra での消費見積もり

| シナリオ | 参加AI | ラウンド | 指揮者 | 評価 | 合計リクエスト |
|---|---|---|---|---|---|
| 軽い議論（① minimal） | 3 | 4 | 5 | 6 | ~20 |
| 標準的な議論（①） | 5 | 6 | 8 | 10 | ~50 |
| 深い議論（① high） | 6 | 8 | 12 | 12 | ~80 |
| コードレビュー（②） | 6パート | 各3回 | 全体会議8 | 12 | ~100 |
| follow-up 付き1日の利用 | — | — | — | — | ~200-300 |

**1日10,000リクエストあれば通常利用では十分**ですが、大量セッションを連続実行する場合は注意が必要です。

### 対策: RateLimitTracker

```python
from datetime import date
from dataclasses import dataclass, field

@dataclass
class RateLimitTracker:
"""日次リクエスト数を追跡し、枯渇を防ぐ"""

daily_limit: int = 10000
safety_margin: float = 0.9  # 90%で警告
request_count: int = 0
last_reset: date = field(default_factory=date.today)

def increment(self, n: int = 1):
self._check_reset()
self.request_count += n

def remaining(self) -> int:
self._check_reset()
return self.daily_limit - self.request_count

def can_proceed(self, estimated_requests: int) -> bool:
"""推定リクエスト数を消費しても安全か判定"""
self._check_reset()
return (self.request_count + estimated_requests) < self.daily_limit * self.safety_margin

def _check_reset(self):
"""日付が変わっていればカウンターリセット"""
if date.today() != self.last_reset:
self.request_count = 0
self.last_reset = date.today()
```

### 実行前チェックの UX

```
📊 予想リクエスト数: 52
🔑 日次残りリクエスト: 9,847 / 10,000
✅ 実行可能

▶ 実行しますか？ [Y/n]:
```

残りが推定消費量の110%を下回る場合は警告:

```
⚠️  予想リクエスト数: 52
🔑 日次残りリクエスト: 48 / 10,000
❌ リクエスト上限に達する可能性があります。
   level を下げるか、明日実行してください。
```

---

## 2.6 大容量リクエスト対応（SHA-256 ヘッダ）

### Lambda@Edge 制約

KotoBuddy のインフラには Lambda@Edge が含まれており、通常の OpenAI SDK 経由では **リクエストボディが1MBを超える場合に失敗**することがあります。

### 対象となるケース

- 機能②（コードレビュー）で大量のソースコードを含むリクエスト
- Phase 3 の最終統合で議論ログ全文を入力する場合
- 画像入力を含むリクエスト

### 対応方法: requests 直叩き + SHA-256 ヘッダ

```python
import hashlib
import json
import requests

def call_large_request(endpoint: str, api_key: str, body: dict) -> dict:
"""1MB超のリクエストを送信する"""

body_bytes = json.dumps(body).encode("utf-8")
sha256_hash = hashlib.sha256(body_bytes).hexdigest()

headers = {
"Content-Type": "application/json",
"Authorization": f"Bearer {api_key}",
"x-amz-content-sha256": sha256_hash,
}

response = requests.post(
f"{endpoint}/chat/completions",
headers=headers,
data=body_bytes,
timeout=120,
)
response.raise_for_status()
return response.json()
```

### AI Orchestra での使い分け

```python
class APIClient:
def call(self, model: str, messages: list, **kwargs) -> dict:
# リクエストサイズを推定
estimated_size = self._estimate_request_size(messages)

if estimated_size > 1_000_000:  # 1MB超
return self._call_large_request(model, messages, **kwargs)
else:
return self._call_sdk(model, messages, **kwargs)
```

### リクエストサイズ制限まとめ

| 制約 | 値 | 対応 |
|---|---|---|
| Lambda@Edge 制限 | ~1MB | `requests` + SHA-256 に切替 |
| API 全体制限 | 6MB 以下 | これを超えるリクエストは分割必須 |

---

## 2.7 プロキシ設定

### 必要な環境

KotoBuddy API はオムロン LAN 内からのみアクセス可能です。環境によってはプロキシ経由でのアクセスが必要です。

### 設定方法

```powershell
# PowerShell
$env:HTTP_PROXY  = "http://185.46.212.88:80"
$env:HTTPS_PROXY = "http://185.46.212.88:80"
```

```bash
# Linux / macOS
export HTTP_PROXY="http://185.46.212.88:80"
export HTTPS_PROXY="http://185.46.212.88:80"
```

### .env ファイルでの管理

AI Orchestra は起動時に `API/.env` ファイルを自動読み込みします（python-dotenv 不要、独自実装）。

```ini
# .env
KOTOBUDDY_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
KOTOBUDDY_ENDPOINT=https://api.rdbuddy.rdinx.rd.omron.com/v1
HTTP_PROXY=http://185.46.212.88:80
HTTPS_PROXY=http://185.46.212.88:80
```

### OpenAI SDK へのプロキシ反映

OpenAI SDK は環境変数 `HTTP_PROXY` / `HTTPS_PROXY` を自動参照します。追加のコード対応は不要です。ただし `requests` ライブラリで直接呼び出す場合（大容量リクエスト時）は明示的に `proxies` を渡します:

```python
proxies = {
"http": os.environ.get("HTTP_PROXY"),
"https": os.environ.get("HTTPS_PROXY"),
}

response = requests.post(url, headers=headers, data=body, proxies=proxies)
```

### 環境変数の優先順位

AI Orchestra は以下の優先順位で設定を読み込みます:

```
1. CLI 引数 (最優先)
2. .env ファイル (プロジェクトルート)
3. 環境変数
4. 互換用フォールバック (AZURE_OPENAI_KEY → KOTOBUDDY_API_KEY)
5. デフォルト値 (settings.yaml)
```

互換性のため、`KOTOBUDDY_*` が未設定の場合は `AZURE_OPENAI_KEY` / `AZURE_OPENAI_ENDPOINT` も参照されます。

### アクセス確認

API に接続できない場合のチェックリスト:

1. **LAN 接続**: オムロン社内 LAN に接続しているか（VPN 含む）
2. **プロキシ**: 必要な環境で `HTTP_PROXY` / `HTTPS_PROXY` が設定されているか
3. **API キー**: 有効期限内か、削除されていないか
4. **エンドポイント**: URL が正しいか（末尾の `/v1` を含む）
5. **日次上限**: 10,000 req/day を超過していないか（超過時は HTTP 401）

---

### 2章まとめ: AI Orchestra が使用するモデルの推奨構成

| Phase / 役割 | モデル | level | 理由 |
|---|---|---|---|
| 計画立案（指揮者） | `gpt-5.4` | high | 1M入力で全コンテキスト読める+深い計画 |
| 進行管理 | `gpt-4.1` | — (temperature=0.3) | 高速・安定・定型処理 |
| 収束判定 | `gpt-4.1` | — (temperature=0) | 確定的な判定 |
| 最終統合 | `claude-sonnet-4-5` | high (budget=16000) | 拡張思考で丁寧に統合 |
| 🧮 理論屋 | `gpt-5.4` | high | 深い推論 |
| 🔬 実験屋 | `gpt-5` | medium | バランス |
| 🤖 実装屋 | `claude-sonnet-4-5` | medium (budget=8000) | コード理解力+思考可視化 |
| 📚 文献屋 | `gpt-5.4` | medium | 広い知識 |
| 😈 穴探し | `claude-sonnet-4-5` | medium (budget=8000) | 論理的な穴探し |
| 🎯 鳥の目 | `gpt-5.4` | high | 俯瞰的思考 |

**1セッション（標準的な議論）の推定消費**:
- リクエスト数: 約50回
- token 数: 約80,000
- 所要時間: 約3〜5分
- 日次上限に対する割合: 0.5%

---
