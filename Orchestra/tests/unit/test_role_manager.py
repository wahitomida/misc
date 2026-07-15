"""``core.role_manager.RoleManager`` のユニットテスト。"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from core.exceptions import (
    ConfigLoadError,
    RoleNotFoundError,
    RoleValidationError,
)
from core.role_manager import (
    REQUIRED_FIELDS,
    SYSTEM_PROMPT_PLACEHOLDERS,
    RoleManager,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_VALID_ROLE_YAML = dedent(
    """\
    role_id: theorist
    display_name: "🧮 理論屋"
    model: gpt-5.4
    default_level: high

    personality:
      traits: ["a", "b"]
      communication_style: "test"
      weakness: "test"

    expertise:
      - 数理モデリング

    domain_tags:
      - machine_learning

    system_prompt: |
      あなたはAI Orchestraの「理論屋」です。

      {orchestrator_instruction}

      {feedback_context}

    evaluation_criteria:
      - name: "c1"
        description: "d1"
      - name: "c2"
        description: "d2"
      - name: "c3"
        description: "d3"

    feedback_history: []
    feedback_stats: {}
    """
)


@pytest.fixture
def roles_dir(tmp_path: Path) -> Path:
    """``theorist.yaml`` を含む一時 roles ディレクトリ。"""
    d = tmp_path / "roles"
    d.mkdir()
    (d / "theorist.yaml").write_text(_VALID_ROLE_YAML, encoding="utf-8")
    return d


def _write_role(roles_dir: Path, name: str, body: str) -> None:
    (roles_dir / f"{name}.yaml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# load_role
# ---------------------------------------------------------------------------


class TestLoadRole:
    """``load_role`` の正常系・異常系。"""

    def test_load_role_returns_dict(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)

        role = manager.load_role("theorist")

        assert role["role_id"] == "theorist"
        assert role["display_name"] == "🧮 理論屋"
        assert role["model"] == "gpt-5.4"

    def test_load_role_caches_result(self, roles_dir: Path) -> None:
        """2 回目以降はキャッシュから返す (ファイルを削除しても読める)。"""
        manager = RoleManager(roles_dir)

        first = manager.load_role("theorist")
        # ファイルを削除
        (roles_dir / "theorist.yaml").unlink()
        second = manager.load_role("theorist")

        assert first is second  # same object from cache

    def test_load_role_missing_raises_role_not_found(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleNotFoundError, match="not found"):
            manager.load_role("nonexistent")

    def test_load_role_with_invalid_yaml_raises_config_load_error(
        self, roles_dir: Path
    ) -> None:
        _write_role(roles_dir, "broken", "not: [valid: yaml")
        manager = RoleManager(roles_dir)

        with pytest.raises(ConfigLoadError, match="Failed to parse"):
            manager.load_role("broken")

    def test_load_role_with_non_mapping_top_level_raises(
        self, roles_dir: Path
    ) -> None:
        _write_role(roles_dir, "wrong_type", "- just\n- a\n- list\n")
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleValidationError, match="must contain a mapping"):
            manager.load_role("wrong_type")


# ---------------------------------------------------------------------------
# _validate_role
# ---------------------------------------------------------------------------


class TestValidation:
    """``_validate_role`` の各種バリデーション。"""

    @pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
    def test_missing_required_field_raises(
        self, roles_dir: Path, missing_field: str
    ) -> None:
        """必須フィールドのいずれかが欠けたら ``RoleValidationError``。"""
        # role_id を欠落させると ファイル名と一致しないが、検証順は最初
        text = _VALID_ROLE_YAML.replace(f"{missing_field}:", f"_{missing_field}:")
        _write_role(roles_dir, "broken_role", text)
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleValidationError, match=missing_field):
            manager.load_role("broken_role")

    def test_invalid_role_id_pattern_raises(self, roles_dir: Path) -> None:
        """大文字始まりは不可。"""
        text = _VALID_ROLE_YAML.replace("role_id: theorist", "role_id: Theorist")
        _write_role(roles_dir, "bad_id", text)
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleValidationError, match="must match pattern"):
            manager.load_role("bad_id")

    def test_role_id_too_long_raises(self, roles_dir: Path) -> None:
        long_id = "a" * 31
        text = _VALID_ROLE_YAML.replace("role_id: theorist", f"role_id: {long_id}")
        _write_role(roles_dir, "long_id", text)
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleValidationError, match="max length"):
            manager.load_role("long_id")

    @pytest.mark.parametrize("placeholder", SYSTEM_PROMPT_PLACEHOLDERS)
    def test_system_prompt_without_placeholder_still_loads(
        self, roles_dir: Path, placeholder: str
    ) -> None:
        """新スキーマ: プレースホルダーは共通テンプレートで付与されるため、
        ロール YAML の system_prompt に含まれていなくてもロード可能。"""
        text = _VALID_ROLE_YAML.replace(placeholder, "")
        _write_role(roles_dir, "no_placeholder", text)
        manager = RoleManager(roles_dir)

        role = manager.load_role("no_placeholder")
        assert role["role_id"] == "theorist"

    def test_system_prompt_empty_raises(self, roles_dir: Path) -> None:
        text = _VALID_ROLE_YAML.replace(
            "system_prompt: |", "system_prompt: \"\"\n_dummy: |"
        )
        _write_role(roles_dir, "empty_prompt", text)
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleValidationError, match="system_prompt"):
            manager.load_role("empty_prompt")

    def test_too_few_evaluation_criteria_raises(self, roles_dir: Path) -> None:
        """3 個未満なら ``RoleValidationError``。"""
        text = _VALID_ROLE_YAML.replace(
            "evaluation_criteria:\n"
            '  - name: "c1"\n'
            '    description: "d1"\n'
            '  - name: "c2"\n'
            '    description: "d2"\n'
            '  - name: "c3"\n'
            '    description: "d3"\n',
            'evaluation_criteria:\n  - name: "c1"\n    description: "d1"\n',
        )
        _write_role(roles_dir, "few_criteria", text)
        manager = RoleManager(roles_dir)

        with pytest.raises(RoleValidationError, match="evaluation_criteria"):
            manager.load_role("few_criteria")


# ---------------------------------------------------------------------------
# list_available_roles
# ---------------------------------------------------------------------------


class TestListAvailableRoles:
    """``list_available_roles`` のサマリ生成。"""

    def test_list_returns_summary_for_each_role(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)

        roles = manager.list_available_roles()

        assert len(roles) == 1
        assert roles[0]["role_id"] == "theorist"
        assert roles[0]["display_name"] == "🧮 理論屋"
        assert roles[0]["model"] == "gpt-5.4"
        assert roles[0]["expertise"] == ["数理モデリング"]
        assert roles[0]["domain_tags"] == ["machine_learning"]
        assert roles[0]["feedback_stats"] == {}

    def test_list_skips_invalid_yaml(
        self, roles_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """壊れた YAML は警告ログを残してスキップする。"""
        _write_role(roles_dir, "broken", "not: [valid: yaml")
        manager = RoleManager(roles_dir)

        with caplog.at_level("WARNING"):
            roles = manager.list_available_roles()

        # theorist のみが残る
        ids = [r["role_id"] for r in roles]
        assert ids == ["theorist"]


# ---------------------------------------------------------------------------
# 実 config/roles/*.yaml を読むスモーク
# ---------------------------------------------------------------------------


class TestRealRolesDirectory:
    """同梱の ``config/roles/`` 配下が全て妥当であること。"""

    def test_all_eight_roles_load_successfully(self) -> None:
        """同梱の 10 ロール (8 デフォルト + 2 カスタム) が全て読み込めてバリデーションを通る。"""
        repo_roles_dir = Path(__file__).resolve().parents[2] / "config" / "roles"

        manager = RoleManager(repo_roles_dir)
        roles = manager.list_available_roles()

        ids = sorted(r["role_id"] for r in roles)
        assert ids == [
            "bird_eye",
            "code_architect",
            "code_reviewer",
            "devil",
            "experimentalist",
            "implementer",
            "literature",
            "matushita_kounosuke",
            "son_masayoshi",
            "theorist",
        ]

    def test_required_fields_are_present_in_each_role(self) -> None:
        repo_roles_dir = Path(__file__).resolve().parents[2] / "config" / "roles"

        manager = RoleManager(repo_roles_dir)
        for summary in manager.list_available_roles():
            role = manager.load_role(summary["role_id"])
            for field in REQUIRED_FIELDS:
                assert field in role, f"{summary['role_id']} missing {field}"


# ---------------------------------------------------------------------------
# CRUD (save_role / delete_role / validate_role_data / is_default_role)
# ---------------------------------------------------------------------------


def _valid_role_payload(role_id: str = "custom_expert") -> dict:
    """バリデーションを通る最小構成のロール定義辞書。"""
    return {
        "role_id": role_id,
        "display_name": "🧪 " + role_id,
        "model": "gpt-4.1",
        "default_level": "medium",
        "personality": {
            "traits": ["論理的", "冷静"],
            "communication_style": "簡潔",
            "weakness": "実装が苦手",
        },
        "expertise": ["testing"],
        "domain_tags": ["general"],
        "system_prompt": (
            "あなたはテスト用ロールです。\n\n"
            "{orchestrator_instruction}\n\n"
            "{feedback_context}\n"
        ),
        "evaluation_criteria": [
            {"name": "c1", "description": "d1"},
            {"name": "c2", "description": "d2"},
            {"name": "c3", "description": "d3"},
        ],
    }


class TestValidateRoleData:
    """``validate_role_data`` は例外を投げず、エラーメッセージのリストを返す。"""

    def test_valid_payload_returns_empty_list(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        assert manager.validate_role_data(_valid_role_payload()) == []

    def test_invalid_role_id_returns_error(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        payload = _valid_role_payload(role_id="Bad Name")
        errors = manager.validate_role_data(payload)
        assert errors
        assert any("role_id" in e for e in errors)

    def test_missing_placeholder_is_allowed(self, roles_dir: Path) -> None:
        """新スキーマ: プレースホルダーが含まれていなくても検証エラーにならない。"""
        manager = RoleManager(roles_dir)
        payload = _valid_role_payload()
        payload["system_prompt"] = "あなたはテストロールです。専門性を发揮してください。"
        errors = manager.validate_role_data(payload)
        assert errors == []

    def test_empty_system_prompt_returns_error(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        payload = _valid_role_payload()
        payload["system_prompt"] = "   "
        errors = manager.validate_role_data(payload)
        assert any("system_prompt" in e for e in errors)

    def test_too_few_criteria_returns_error(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        payload = _valid_role_payload()
        payload["evaluation_criteria"] = payload["evaluation_criteria"][:2]
        errors = manager.validate_role_data(payload)
        assert any("evaluation_criteria" in e for e in errors)


class TestIsDefaultRole:
    """``DEFAULT_ROLES`` 判定。"""

    def test_default_roles_are_recognized(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        for rid in ("theorist", "devil", "bird_eye", "code_reviewer"):
            assert manager.is_default_role(rid) is True

    def test_custom_role_is_not_default(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        assert manager.is_default_role("custom_expert") is False


class TestSaveRole:
    """``save_role`` の正常系と、既存ファイル上書き。"""

    def test_save_role_creates_yaml_file(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        manager.save_role(_valid_role_payload("newbie"))

        path = roles_dir / "newbie.yaml"
        assert path.exists()
        loaded = manager.load_role("newbie")
        assert loaded["role_id"] == "newbie"
        assert loaded["personality"]["traits"] == ["論理的", "冷静"]

    def test_save_role_updates_existing(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        payload = _valid_role_payload("newbie")
        manager.save_role(payload)

        payload["display_name"] = "🧪 更新後"
        manager.save_role(payload)

        # キャッシュがクリアされて最新値が読める
        loaded = manager.load_role("newbie")
        assert loaded["display_name"] == "🧪 更新後"

    def test_save_role_with_invalid_data_raises(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        bad = _valid_role_payload("newbie")
        # 新スキーマでは system_prompt が空ならエラー
        bad["system_prompt"] = ""
        with pytest.raises(RoleValidationError):
            manager.save_role(bad)
        # ファイルは生成されない
        assert not (roles_dir / "newbie.yaml").exists()


class TestDeleteRole:
    """``delete_role`` — カスタムのみ削除可、デフォルトは保護。"""

    def test_delete_custom_role_removes_yaml(self, roles_dir: Path) -> None:
        from core.exceptions import RoleProtectedError  # noqa: F401 (import check)

        manager = RoleManager(roles_dir)
        manager.save_role(_valid_role_payload("temp_role"))
        assert (roles_dir / "temp_role.yaml").exists()

        manager.delete_role("temp_role")
        assert not (roles_dir / "temp_role.yaml").exists()

    def test_delete_default_role_raises_protected(self, roles_dir: Path) -> None:
        from core.exceptions import RoleProtectedError

        manager = RoleManager(roles_dir)
        with pytest.raises(RoleProtectedError):
            manager.delete_role("theorist")
        # ファイルは残ったまま
        assert (roles_dir / "theorist.yaml").exists()

    def test_delete_missing_role_raises_not_found(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        with pytest.raises(RoleNotFoundError):
            manager.delete_role("does_not_exist")


class TestRefreshCache:
    """``refresh_cache`` はキャッシュを全消しする。"""

    def test_refresh_cache_forces_reload(self, roles_dir: Path) -> None:
        manager = RoleManager(roles_dir)
        # 1 回ロードしてキャッシュに載せる
        first = manager.load_role("theorist")
        assert "theorist" in manager._cache  # noqa: SLF001

        manager.refresh_cache()
        assert manager._cache == {}  # noqa: SLF001

        # 再ロードすると同じ内容を返す
        second = manager.load_role("theorist")
        assert first == second
