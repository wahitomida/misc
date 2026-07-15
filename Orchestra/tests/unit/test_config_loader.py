"""``core.config_loader.Settings`` のユニットテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config_loader import (
    DEFAULT_EXPERTISE_LEVEL,
    Settings,
)
from core.exceptions import ConfigLoadError

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

MINIMAL_YAML = """\
version: "1.2.3"

time_limits:
  idea_default_sec: 300
  min_sec: 60

agents:
  min_agents: 2

api:
  daily_request_limit: 10000
  retry:
    max_retries: 3
    timeouts:
      gpt-4.1: 30
      gpt-5.4: 90
      default: 60

level_time_estimates:
  minimal: 3
  low: 5
  medium: 10
  high: 20

model_time_multiplier:
  gpt-5.4: 1.0
  gpt-4.1: 0.5

expertise_levels:
  beginner:
    description: "beginner"
    max_tokens: 400
  intermediate:
    description: "intermediate"
    max_tokens: 300
  expert:
    description: "expert"
    max_tokens: 200

default_expertise: intermediate
"""


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """``settings.yaml`` を含む一時 config ディレクトリ。"""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(MINIMAL_YAML, encoding="utf-8")
    return cfg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """テスト間で環境変数の影響を遮断する。"""
    for key in (
        "KOTOBUDDY_API_KEY",
        "KOTOBUDDY_ENDPOINT",
        "KOTOBUDDY_MODE",
        "API_VERSION",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# YAML ロード
# ---------------------------------------------------------------------------


class TestSettingsLoad:
    """``Settings.load`` の YAML 読み込みに関するテスト。"""

    def test_load_with_valid_yaml_populates_sections(self, config_dir: Path) -> None:
        """正常な YAML を読むと全セクションが反映される。"""
        settings = Settings.load(config_dir=config_dir)

        assert settings.version == "1.2.3"
        assert settings.time_limits["idea_default_sec"] == 300
        assert settings.agents["min_agents"] == 2
        assert settings.default_expertise == "intermediate"

    def test_load_when_settings_yaml_missing_raises_config_load_error(
        self, tmp_path: Path
    ) -> None:
        """settings.yaml が無いと ConfigLoadError。"""
        empty_dir = tmp_path / "empty_config"
        empty_dir.mkdir()

        with pytest.raises(ConfigLoadError, match="settings.yaml not found"):
            Settings.load(config_dir=empty_dir)

    def test_load_when_yaml_is_broken_raises_config_load_error(self, tmp_path: Path) -> None:
        """YAML として不正な内容なら ConfigLoadError。"""
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "settings.yaml").write_text("not: [valid: yaml", encoding="utf-8")

        with pytest.raises(ConfigLoadError, match="Failed to parse"):
            Settings.load(config_dir=cfg)

    def test_load_when_yaml_top_level_is_not_mapping_raises(self, tmp_path: Path) -> None:
        """トップレベルがマッピングでないと ConfigLoadError。"""
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "settings.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

        with pytest.raises(ConfigLoadError, match="must be a mapping"):
            Settings.load(config_dir=cfg)


# ---------------------------------------------------------------------------
# .env パーサー / 環境変数解決
# ---------------------------------------------------------------------------


class TestEnvFileParsing:
    """独自 .env パーサーの挙動。"""

    def test_env_file_values_override_process_env(
        self,
        config_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.env の値はプロセス環境変数より優先される。"""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "KOTOBUDDY_API_KEY=from-env-file\n"
            "KOTOBUDDY_ENDPOINT=https://example.com/v1\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("KOTOBUDDY_API_KEY", "from-process-env")

        settings = Settings.load(config_dir=config_dir, env_file=env_path)

        assert settings.api_key == "from-env-file"
        assert settings.endpoint == "https://example.com/v1"

    def test_env_file_supports_comments_export_and_quotes(
        self,
        config_dir: Path,
        tmp_path: Path,
    ) -> None:
        """``#`` コメント、``export`` 接頭辞、引用符を正しく扱う。"""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# leading comment\n"
            "\n"
            "export KOTOBUDDY_API_KEY=\"quoted-key\"  # trailing comment\n"
            "KOTOBUDDY_ENDPOINT='https://quoted.example/v1'\n"
            "KOTOBUDDY_MODE=openai\n",
            encoding="utf-8",
        )

        settings = Settings.load(config_dir=config_dir, env_file=env_path)

        assert settings.api_key == "quoted-key"
        assert settings.endpoint == "https://quoted.example/v1"
        assert settings.mode == "openai"

    def test_env_file_absent_is_not_an_error(
        self,
        config_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.env が無くてもプロセス環境変数が拾われる。"""
        monkeypatch.setenv("KOTOBUDDY_API_KEY", "from-process-env")
        monkeypatch.setenv("KOTOBUDDY_ENDPOINT", "https://process.example/v1")

        settings = Settings.load(config_dir=config_dir, env_file=tmp_path / "missing.env")

        assert settings.api_key == "from-process-env"
        assert settings.endpoint == "https://process.example/v1"


class TestCredentialPrecedence:
    """認証情報の優先順位 (CLI > .env > process env > AZURE フォールバック)。"""

    def test_cli_overrides_take_highest_priority(
        self,
        config_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CLI 引数が全てに勝つ。"""
        env_path = tmp_path / ".env"
        env_path.write_text("KOTOBUDDY_API_KEY=from-env-file\n", encoding="utf-8")
        monkeypatch.setenv("KOTOBUDDY_API_KEY", "from-process-env")

        settings = Settings.load(
            config_dir=config_dir,
            env_file=env_path,
            cli_overrides={"KOTOBUDDY_API_KEY": "from-cli"},
        )

        assert settings.api_key == "from-cli"

    def test_azure_openai_fallback_used_when_kotobuddy_missing(
        self,
        config_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """KOTOBUDDY_* が未設定なら AZURE_OPENAI_* を見る。"""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://azure.example/")
        monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

        settings = Settings.load(
            config_dir=config_dir,
            env_file=tmp_path / "missing.env",
        )

        assert settings.api_key == "azure-key"
        assert settings.endpoint == "https://azure.example/"
        assert settings.api_version == "2024-12-01-preview"

    def test_kotobuddy_takes_priority_over_azure_fallback(
        self,
        config_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """両方ある場合は KOTOBUDDY_* が勝つ。"""
        monkeypatch.setenv("KOTOBUDDY_API_KEY", "primary")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fallback")

        settings = Settings.load(
            config_dir=config_dir,
            env_file=tmp_path / "missing.env",
        )

        assert settings.api_key == "primary"

    def test_missing_credentials_result_in_none(
        self,
        config_dir: Path,
        tmp_path: Path,
    ) -> None:
        """どこにも値がなければ None。"""
        settings = Settings.load(
            config_dir=config_dir,
            env_file=tmp_path / "missing.env",
        )

        assert settings.api_key is None
        assert settings.endpoint is None
        assert settings.mode is None
        assert settings.api_version is None


# ---------------------------------------------------------------------------
# アクセサ
# ---------------------------------------------------------------------------


class TestGetTimeout:
    """``Settings.get_timeout`` のテスト。"""

    def test_get_timeout_returns_model_specific_value(self, config_dir: Path) -> None:
        """既知のモデルはモデル別タイムアウトを返す。"""
        settings = Settings.load(config_dir=config_dir)

        assert settings.get_timeout("gpt-4.1") == 30
        assert settings.get_timeout("gpt-5.4") == 90

    def test_get_timeout_falls_back_to_default(self, config_dir: Path) -> None:
        """未定義モデルは default にフォールバック。"""
        settings = Settings.load(config_dir=config_dir)

        assert settings.get_timeout("unknown-model-xyz") == 60


class TestGetLevelTime:
    """``Settings.get_level_time`` のテスト。"""

    def test_get_level_time_without_model_returns_base(self, config_dir: Path) -> None:
        """model 未指定なら基準値をそのまま返す。"""
        settings = Settings.load(config_dir=config_dir)

        assert settings.get_level_time("medium") == 10
        assert settings.get_level_time("high") == 20

    def test_get_level_time_applies_model_multiplier(self, config_dir: Path) -> None:
        """model 指定時は補正係数が掛かる。"""
        settings = Settings.load(config_dir=config_dir)

        # medium=10, gpt-4.1=0.5 → 5.0
        assert settings.get_level_time("medium", model="gpt-4.1") == pytest.approx(5.0)
        # high=20, gpt-5.4=1.0 → 20.0
        assert settings.get_level_time("high", model="gpt-5.4") == pytest.approx(20.0)

    def test_get_level_time_unknown_level_returns_default(self, config_dir: Path) -> None:
        """未定義の level は既定値 (10 秒)。"""
        settings = Settings.load(config_dir=config_dir)

        assert settings.get_level_time("unknown-level") == 10


class TestGetExpertiseConfig:
    """``Settings.get_expertise_config`` のテスト。"""

    def test_get_expertise_config_returns_level_dict(self, config_dir: Path) -> None:
        """指定レベルの辞書を返す。"""
        settings = Settings.load(config_dir=config_dir)

        config = settings.get_expertise_config("expert")
        assert config["description"] == "expert"
        assert config["max_tokens"] == 200

    def test_get_expertise_config_falls_back_to_intermediate(self, config_dir: Path) -> None:
        """未知のレベルは intermediate にフォールバック。"""
        settings = Settings.load(config_dir=config_dir)

        config = settings.get_expertise_config("nonexistent")
        assert config["description"] == DEFAULT_EXPERTISE_LEVEL


# ---------------------------------------------------------------------------
# 実 settings.yaml に対するスモーク
# ---------------------------------------------------------------------------


class TestRealSettingsYaml:
    """リポジトリ同梱の ``config/settings.yaml`` が読み込めることを確認する。"""

    def test_repository_settings_loads_without_error(self) -> None:
        """同梱の settings.yaml が壊れていないこと。"""
        repo_config_dir = Path(__file__).resolve().parents[2] / "config"

        settings = Settings.load(config_dir=repo_config_dir)

        # 17章のキー要素が読めていることを最低限確認
        assert settings.version == "1.0.0"
        assert settings.time_limits["idea_default_sec"] == 300
        assert settings.agents["max_agents"] == 8
        assert settings.get_timeout("gpt-4.1") == 30
        # planner 用: 圧縮版 PLANNING_PROMPT でも余裕を持たせるため 180 秒に延長済み
        assert settings.get_timeout("gpt-5.4") == 180
        # Phase 3 で LEVEL_TIME_MAP を実測値に短縮: medium=5, gpt-4.1=0.5 → 2.5
        assert settings.get_level_time("medium", model="gpt-4.1") == pytest.approx(2.5)
        expert_cfg = settings.get_expertise_config("expert")
        assert expert_cfg["max_tokens"] == 200
