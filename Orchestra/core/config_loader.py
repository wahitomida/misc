"""settings.yaml と環境変数を統合してロードするモジュール。

優先順位 (高 → 低):
    1. CLI 引数 (``cli_overrides``)
    2. ``.env`` ファイル (プロジェクトルート)
    3. プロセス環境変数 (``os.environ``)
    4. 互換用フォールバック (``AZURE_OPENAI_*`` → ``KOTOBUDDY_*``)
    5. ``settings.yaml`` のデフォルト値

設計書: ``doc/17_settings.md``, ``doc/02_api_specification.md`` §2.7
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigLoadError

# Constants
DEFAULT_CONFIG_DIR = Path("config")
DEFAULT_TIMEOUT_SEC = 60
DEFAULT_EXPERTISE_LEVEL = "intermediate"
DEFAULT_LEVEL_TIME_SEC = 10
DEFAULT_MODEL_MULTIPLIER = 1.0

# 環境変数名 (KotoBuddy 一次)
ENV_API_KEY = "KOTOBUDDY_API_KEY"
ENV_ENDPOINT = "KOTOBUDDY_ENDPOINT"
ENV_MODE = "KOTOBUDDY_MODE"
ENV_API_VERSION = "API_VERSION"

# 互換用フォールバック (Azure OpenAI 命名)
ENV_API_KEY_FALLBACK = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY")
ENV_ENDPOINT_FALLBACK = ("AZURE_OPENAI_ENDPOINT",)
ENV_API_VERSION_FALLBACK = ("AZURE_OPENAI_API_VERSION",)

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """``settings.yaml`` + 環境変数の統合表現。

    Attributes:
        time_limits: 時間制限関連 (§17.1.1)。
        agents: エージェント上限 (§17.1.2)。
        convergence: 収束判定 (§17.1.3)。
        conversation_style: 会話スタイル (§17.2.1)。
        utterance_length: 発言長制御 (§17.2.2)。
        round_utterances: ラウンド内発言制御 (§17.2.3)。
        speaking_rules: 発言ルール (§17.2.4)。
        expertise_levels: expertise レベル別設定 (§17.3)。
        default_expertise: CLI 未指定時のデフォルト expertise レベル。
        api: API 制約 + retry/timeouts (§17.4)。
        level_time_estimates: level 別推定時間 (§17.5)。
        model_time_multiplier: モデル別補正係数 (§17.5)。
        feedback: フィードバック設定 (§17.6)。
        fallback: フォールバック設定 (§17.7)。
        code_review: コードレビュー固有設定 (§17.8)。
        output: 出力設定 (§17.9)。
        models: デフォルトモデル設定 (§17.9 末尾)。
        version: 設定ファイルのバージョン。
        api_key: KotoBuddy API キー (環境変数経由)。
        endpoint: KotoBuddy エンドポイント URL。
        mode: 接続モード ("openai" | "azure" | None で自動判定)。
        api_version: Azure モード用 API バージョン。
    """

    # YAML セクション
    time_limits: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    convergence: dict[str, Any] = field(default_factory=dict)
    conversation_style: dict[str, Any] = field(default_factory=dict)
    utterance_length: dict[str, Any] = field(default_factory=dict)
    round_utterances: dict[str, Any] = field(default_factory=dict)
    speaking_rules: dict[str, Any] = field(default_factory=dict)
    expertise_levels: dict[str, Any] = field(default_factory=dict)
    default_expertise: str = DEFAULT_EXPERTISE_LEVEL
    api: dict[str, Any] = field(default_factory=dict)
    level_time_estimates: dict[str, Any] = field(default_factory=dict)
    model_time_multiplier: dict[str, Any] = field(default_factory=dict)
    feedback: dict[str, Any] = field(default_factory=dict)
    fallback: dict[str, Any] = field(default_factory=dict)
    code_review: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)
    version: str = "0.0.0"

    # 環境変数由来
    api_key: str | None = None
    endpoint: str | None = None
    mode: str | None = None
    api_version: str | None = None

    # ------------------------------------------------------------------
    # ロード
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        config_dir: Path = DEFAULT_CONFIG_DIR,
        cli_overrides: dict[str, str] | None = None,
        env_file: Path | None = None,
    ) -> "Settings":
        """``settings.yaml`` と環境変数を統合した ``Settings`` を返す。

        Args:
            config_dir: ``settings.yaml`` を格納するディレクトリ。
            cli_overrides: CLI 引数による上書き値 (``api_key``, ``endpoint``,
                ``mode``, ``api_version``)。最優先で適用される。
            env_file: 読み込む ``.env`` ファイルのパス。未指定の場合は
                ``config_dir`` の親直下の ``.env`` を探索する。

        Returns:
            統合済みの ``Settings`` インスタンス。

        Raises:
            ConfigLoadError: ``settings.yaml`` が存在しない、または YAML として
                解釈できない場合。
        """
        yaml_data = cls._load_yaml(config_dir)
        env_data = cls._load_env_file(env_file or _default_env_path(config_dir))
        resolved = cls._resolve_credentials(
            cli_overrides=cli_overrides or {},
            env_file_data=env_data,
            process_env=os.environ,
        )

        return cls(
            time_limits=yaml_data.get("time_limits", {}),
            agents=yaml_data.get("agents", {}),
            convergence=yaml_data.get("convergence", {}),
            conversation_style=yaml_data.get("conversation_style", {}),
            utterance_length=yaml_data.get("utterance_length", {}),
            round_utterances=yaml_data.get("round_utterances", {}),
            speaking_rules=yaml_data.get("speaking_rules", {}),
            expertise_levels=yaml_data.get("expertise_levels", {}),
            default_expertise=yaml_data.get("default_expertise", DEFAULT_EXPERTISE_LEVEL),
            api=yaml_data.get("api", {}),
            level_time_estimates=yaml_data.get("level_time_estimates", {}),
            model_time_multiplier=yaml_data.get("model_time_multiplier", {}),
            feedback=yaml_data.get("feedback", {}),
            fallback=yaml_data.get("fallback", {}),
            code_review=yaml_data.get("code_review", {}),
            output=yaml_data.get("output", {}),
            models=yaml_data.get("models", {}),
            version=str(yaml_data.get("version", "0.0.0")),
            api_key=resolved["api_key"],
            endpoint=resolved["endpoint"],
            mode=resolved["mode"],
            api_version=resolved["api_version"],
        )

    # ------------------------------------------------------------------
    # アクセサ
    # ------------------------------------------------------------------

    def get_timeout(self, model: str) -> int:
        """モデル別タイムアウト値を秒で取得する。

        Args:
            model: モデル名 (例: ``"gpt-5.4"``)。

        Returns:
            タイムアウト秒数。未定義のモデルは ``default`` 値、それも
            なければ ``DEFAULT_TIMEOUT_SEC``。
        """
        timeouts = self.api.get("retry", {}).get("timeouts", {})
        return int(timeouts.get(model, timeouts.get("default", DEFAULT_TIMEOUT_SEC)))

    def get_level_time(self, level: str, model: str | None = None) -> float:
        """level × model の推定発話時間 (秒) を返す。

        Args:
            level: 発言レベル (``minimal`` / ``low`` / ``medium`` / ``high``)。
            model: モデル名。指定するとモデル別補正係数が掛けられる。

        Returns:
            推定発話時間 (秒)。
        """
        base = float(self.level_time_estimates.get(level, DEFAULT_LEVEL_TIME_SEC))
        if model is None:
            return base
        multiplier = float(self.model_time_multiplier.get(model, DEFAULT_MODEL_MULTIPLIER))
        return base * multiplier

    def get_expertise_config(self, level: str) -> dict[str, Any]:
        """expertise レベルの設定辞書を取得する。

        Args:
            level: ``beginner`` / ``intermediate`` / ``expert``。

        Returns:
            設定辞書。未定義のレベルは ``intermediate`` にフォールバックする。
        """
        fallback = self.expertise_levels.get(DEFAULT_EXPERTISE_LEVEL, {})
        return self.expertise_levels.get(level, fallback)

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _load_yaml(config_dir: Path) -> dict[str, Any]:
        """``settings.yaml`` を読み込んで辞書として返す。"""
        settings_path = Path(config_dir) / "settings.yaml"
        if not settings_path.exists():
            raise ConfigLoadError(f"settings.yaml not found: {settings_path}")
        try:
            with settings_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigLoadError(f"Failed to parse {settings_path}: {e}") from e
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ConfigLoadError(
                f"settings.yaml must be a mapping at top level, got {type(data).__name__}"
            )
        return data

    @staticmethod
    def _load_env_file(env_path: Path) -> dict[str, str]:
        """``.env`` ファイルをパースして辞書として返す (存在しなければ空)。

        Args:
            env_path: ``.env`` ファイルのパス。

        Returns:
            ``KEY: value`` の辞書。``export KEY=value`` 形式や、値の前後の
            シングル/ダブルクォートも除去する。
        """
        if not env_path.exists():
            return {}
        result: dict[str, str] = {}
        try:
            text = env_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to read %s: %s", env_path, e)
            return {}

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = _strip_inline_comment(value).strip()
            value = _unquote(value)
            result[key] = value
        return result

    @staticmethod
    def _resolve_credentials(
        cli_overrides: dict[str, str],
        env_file_data: dict[str, str],
        process_env: dict[str, str] | os._Environ,
    ) -> dict[str, str | None]:
        """優先順位に従って認証情報を解決する。

        優先順位: CLI > .env > os.environ > フォールバック (AZURE_OPENAI_*)
        """

        def pick(*keys: str) -> str | None:
            """順番にキーを試し、最初に見つかった非空値を返す。"""
            for k in keys:
                if k in cli_overrides and cli_overrides[k]:
                    return str(cli_overrides[k])
            for k in keys:
                if k in env_file_data and env_file_data[k]:
                    return env_file_data[k]
            for k in keys:
                if process_env.get(k):
                    return process_env[k]
            return None

        api_key = (
            pick(ENV_API_KEY)
            or pick(*ENV_API_KEY_FALLBACK)
        )
        endpoint = (
            pick(ENV_ENDPOINT)
            or pick(*ENV_ENDPOINT_FALLBACK)
        )
        mode = pick(ENV_MODE)
        api_version = (
            pick(ENV_API_VERSION)
            or pick(*ENV_API_VERSION_FALLBACK)
        )

        return {
            "api_key": api_key,
            "endpoint": endpoint,
            "mode": mode,
            "api_version": api_version,
        }


# ----------------------------------------------------------------------
# モジュールレベルヘルパー
# ----------------------------------------------------------------------


def _default_env_path(config_dir: Path) -> Path:
    """``config_dir`` の親ディレクトリ直下にある ``.env`` のパスを返す。"""
    return Path(config_dir).resolve().parent / ".env"


def _strip_inline_comment(value: str) -> str:
    """引用符の外側にある ``#`` 以降をコメントとして除去する。"""
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return value[:i]
    return value


def _unquote(value: str) -> str:
    """値全体を囲むシングル/ダブルクォートを取り除く。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
