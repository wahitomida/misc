"""ロール YAML の読み込み・キャッシュ・バリデーション。

設計書: ``doc/07_role_definitions.md`` §7.1, §7.4, ``doc/06_agent.md`` §6.2
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .exceptions import (
    ConfigLoadError,
    RoleNotFoundError,
    RoleProtectedError,
    RoleValidationError,
)

# Constants
REQUIRED_FIELDS: tuple[str, ...] = (
    "role_id",
    "display_name",
    "model",
    "system_prompt",
)

# 新スキーマ (AI 自動生成フロー) で導入された自由記述フィールド。
# 任意で、空でも保存可能。上限のみ検証する。UI では description に統合入力する
# ため、実質は description が主フィールド。
OPTIONAL_TEXT_FIELDS: tuple[str, ...] = (
    "description",
    "perspective",
    "tone",
)
OPTIONAL_TEXT_MAX_LENGTH = 1500

ROLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
ROLE_ID_MAX_LENGTH = 30
ROLE_ID_MIN_LENGTH = 2

# 旧スキーマの system_prompt に含まれていたプレースホルダ。共通テンプレート
# (config/role_base_template.txt) が付与するため、新規ロールでは system_prompt
# に含める必要はない。含まれていても許容する。
SYSTEM_PROMPT_PLACEHOLDERS: tuple[str, ...] = (
    "{orchestrator_instruction}",
    "{feedback_context}",
)
SYSTEM_PROMPT_MAX_LENGTH = 5000

EVALUATION_CRITERIA_MIN = 3
EVALUATION_CRITERIA_MAX = 5

# 削除・置換禁止のデフォルトロール群
DEFAULT_ROLES: frozenset[str] = frozenset({
    "theorist",
    "experimentalist",
    "implementer",
    "literature",
    "devil",
    "bird_eye",
    "code_architect",
    "code_reviewer",
})

# 保存時に上書きしないフィールド (feedback は蓄積系なので保護)
PROTECTED_FIELDS_ON_UPDATE: tuple[str, ...] = (
    "feedback_history",
    "feedback_stats",
)

logger = logging.getLogger(__name__)


class RoleManager:
    """``config/roles/*.yaml`` の読み込みと管理。

    Attributes:
        roles_dir: ロール YAML を格納するディレクトリ。
    """

    def __init__(self, roles_dir: Path) -> None:
        """Args: roles_dir: ロール YAML のディレクトリ。"""
        self.roles_dir = Path(roles_dir)
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def load_role(self, role_id: str) -> dict[str, Any]:
        """``role_id`` に対応する YAML を読み込んで辞書として返す。

        Args:
            role_id: ロール識別子 (ファイル名 stem)。

        Returns:
            ロール定義辞書 (バリデーション済み)。

        Raises:
            RoleNotFoundError: 該当 YAML が存在しない。
            RoleValidationError: バリデーションに失敗。
            ConfigLoadError: YAML として解釈不能。
        """
        if role_id in self._cache:
            return self._cache[role_id]

        role_path = self.roles_dir / f"{role_id}.yaml"
        if not role_path.exists():
            raise RoleNotFoundError(
                f"Role '{role_id}' not found at {role_path}"
            )

        try:
            with role_path.open("r", encoding="utf-8") as f:
                role = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigLoadError(f"Failed to parse {role_path}: {e}") from e

        if not isinstance(role, dict):
            raise RoleValidationError(
                f"Role file {role_path} must contain a mapping at top level, "
                f"got {type(role).__name__}"
            )

        self._validate_role(role)
        self._cache[role_id] = role
        return role

    def list_available_roles(self) -> list[dict[str, Any]]:
        """利用可能な全ロールのサマリを返す。

        Returns:
            各要素が ``{"role_id", "display_name", "description",
            "perspective", "tone", "expertise", "domain_tags", "model",
            "feedback_stats"}`` を持つ辞書のリスト。``role_id`` の辞書順。
        """
        summaries: list[dict[str, Any]] = []
        for yaml_path in sorted(self.roles_dir.glob("*.yaml")):
            try:
                role = self.load_role(yaml_path.stem)
            except (RoleValidationError, RoleNotFoundError, ConfigLoadError) as e:
                logger.warning("Skipping role %s: %s", yaml_path.name, e)
                continue
            summaries.append(
                {
                    "role_id": role["role_id"],
                    "display_name": role["display_name"],
                    "description": role.get("description", ""),
                    "perspective": role.get("perspective", ""),
                    "tone": role.get("tone", ""),
                    "expertise": role.get("expertise", []),
                    "domain_tags": role.get("domain_tags", []),
                    "model": role.get("model", "gpt-4.1"),
                    "feedback_stats": role.get("feedback_stats", {}),
                }
            )
        return summaries

    # ------------------------------------------------------------------
    # バリデーション
    # ------------------------------------------------------------------

    def _validate_role(self, role: dict[str, Any]) -> None:
        """ロール辞書を検証する。

        新スキーマでは必須フィールドは ``REQUIRED_FIELDS`` の 4 項目のみ。
        ``personality`` / ``expertise`` / ``evaluation_criteria`` は
        後方互換のため任意扱いで、存在する場合のみ型を検証する。

        Args:
            role: ロール定義辞書。

        Raises:
            RoleValidationError: 必須フィールドの欠落 / 値の不正。
        """
        role_id = role.get("role_id", "?")

        # 必須フィールドの存在
        for field in REQUIRED_FIELDS:
            if field not in role:
                raise RoleValidationError(
                    f"Role '{role_id}' missing required field: '{field}'"
                )

        # role_id のパターン
        actual_role_id = role["role_id"]
        if not isinstance(actual_role_id, str):
            raise RoleValidationError(
                f"role_id must be a string, got {type(actual_role_id).__name__}"
            )
        if len(actual_role_id) > ROLE_ID_MAX_LENGTH:
            raise RoleValidationError(
                f"role_id '{actual_role_id}' exceeds max length "
                f"{ROLE_ID_MAX_LENGTH}"
            )
        if not ROLE_ID_PATTERN.match(actual_role_id):
            raise RoleValidationError(
                f"role_id '{actual_role_id}' must match pattern "
                f"{ROLE_ID_PATTERN.pattern}"
            )

        # system_prompt: 型と長さのみ検証。プレースホルダは共通テンプレートで
        # 付与されるため必須ではない (含まれていても許容)。
        system_prompt = role["system_prompt"]
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise RoleValidationError(
                f"Role '{actual_role_id}' system_prompt must be a non-empty string"
            )
        if len(system_prompt) > SYSTEM_PROMPT_MAX_LENGTH:
            raise RoleValidationError(
                f"Role '{actual_role_id}' system_prompt exceeds "
                f"{SYSTEM_PROMPT_MAX_LENGTH} chars"
            )

        # evaluation_criteria (任意): 存在する場合のみ 3〜5 件を検証
        criteria = role.get("evaluation_criteria")
        if criteria is not None:
            if not isinstance(criteria, list):
                raise RoleValidationError(
                    f"Role '{actual_role_id}' evaluation_criteria must be a list"
                )
            if criteria and not (
                EVALUATION_CRITERIA_MIN <= len(criteria) <= EVALUATION_CRITERIA_MAX
            ):
                raise RoleValidationError(
                    f"Role '{actual_role_id}' evaluation_criteria must have "
                    f"{EVALUATION_CRITERIA_MIN}-{EVALUATION_CRITERIA_MAX} items, "
                    f"got {len(criteria)}"
                )

    # ------------------------------------------------------------------
    # public API: CRUD
    # ------------------------------------------------------------------

    def is_default_role(self, role_id: str) -> bool:
        """``role_id`` がデフォルトロール (削除不可) か判定する。"""
        return role_id in DEFAULT_ROLES

    def refresh_cache(self) -> None:
        """内部キャッシュを全消しする。次回 load 時に再読み込みされる。"""
        self._cache.clear()

    def validate_role_data(self, role_data: dict[str, Any]) -> list[str]:
        """ロール定義辞書を検証し、エラーメッセージのリストを返す。

        ``_validate_role`` の非例外版。空リストならバリデーション OK。

        新スキーマの必須項目は ``role_id``/``display_name``/``model``/
        ``system_prompt`` の 4 個。``description``/``perspective``/``tone``
        や ``domain_tags``/``evaluation_criteria`` は任意 (存在する場合
        のみ型・上限を検証)。

        Args:
            role_data: ロール定義辞書。

        Returns:
            人間可読なエラーメッセージのリスト (空 = 検証成功)。
        """
        errors: list[str] = []
        if not isinstance(role_data, dict):
            return [f"ロール定義は辞書である必要があります: got {type(role_data).__name__}"]

        # 必須フィールドの存在
        for field in REQUIRED_FIELDS:
            if field not in role_data:
                errors.append(f"必須フィールド '{field}' が不足しています")
        if errors:
            return errors

        role_id = role_data.get("role_id", "")
        errors.extend(_validate_role_id(role_id))
        errors.extend(_validate_display_name(role_data.get("display_name", "")))
        errors.extend(_validate_model(role_data.get("model", "")))
        errors.extend(_validate_system_prompt(role_data.get("system_prompt", "")))

        # 任意テキストフィールド (description / perspective / tone): 空でも OK、
        # 上限のみ検証。
        for field in OPTIONAL_TEXT_FIELDS:
            if field in role_data:
                errors.extend(_validate_optional_text(role_data[field], field))

        # 任意の構造フィールド: 存在する場合のみ検証
        if "personality" in role_data and role_data["personality"]:
            errors.extend(_validate_personality(role_data["personality"]))
        if role_data.get("expertise"):
            errors.extend(_validate_string_list(role_data["expertise"], "expertise"))
        if role_data.get("domain_tags"):
            errors.extend(_validate_string_list(role_data["domain_tags"], "domain_tags"))
        if role_data.get("evaluation_criteria"):
            errors.extend(
                _validate_evaluation_criteria(role_data["evaluation_criteria"])
            )
        return errors

    def save_role(self, role_data: dict[str, Any]) -> None:
        """ロール定義を YAML として保存する (新規/上書き共通)。

        Args:
            role_data: バリデーション済みのロール辞書。

        Raises:
            RoleValidationError: バリデーションエラー。
        """
        errors = self.validate_role_data(role_data)
        if errors:
            raise RoleValidationError("; ".join(errors))

        role_id = role_data["role_id"]
        path = self.roles_dir / f"{role_id}.yaml"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(
                    role_data,
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )
        except OSError as e:
            raise ConfigLoadError(f"Failed to write {path}: {e}") from e

        self._cache.pop(role_id, None)

    def delete_role(self, role_id: str) -> None:
        """ロール YAML を削除する。デフォルトロールは削除不可。

        Args:
            role_id: 削除対象のロール識別子。

        Raises:
            RoleProtectedError: デフォルトロールを指定した場合。
            RoleNotFoundError: 対応する YAML が存在しない場合。
        """
        if self.is_default_role(role_id):
            raise RoleProtectedError(
                f"Default role '{role_id}' cannot be deleted"
            )
        if not ROLE_ID_PATTERN.match(role_id or ""):
            raise RoleNotFoundError(f"Invalid role_id: {role_id}")
        path = self.roles_dir / f"{role_id}.yaml"
        if not path.exists():
            raise RoleNotFoundError(f"Role '{role_id}' not found at {path}")
        try:
            path.unlink()
        except OSError as e:
            raise ConfigLoadError(f"Failed to delete {path}: {e}") from e

        self._cache.pop(role_id, None)


# ---------------------------------------------------------------------------
# validate_role_data のヘルパー (モジュールレベルで純粋関数化)
# ---------------------------------------------------------------------------


def _validate_role_id(role_id: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(role_id, str) or not role_id:
        return ["role_id は空でない文字列である必要があります"]
    if len(role_id) < ROLE_ID_MIN_LENGTH:
        errors.append(f"role_id は {ROLE_ID_MIN_LENGTH} 文字以上である必要があります")
    if len(role_id) > ROLE_ID_MAX_LENGTH:
        errors.append(
            f"role_id は {ROLE_ID_MAX_LENGTH} 文字以下である必要があります"
        )
    if not ROLE_ID_PATTERN.match(role_id):
        errors.append(
            "role_id は英小文字/数字/アンダースコアのみで、先頭は英小文字である必要があります"
        )
    return errors


def _validate_display_name(name: Any) -> list[str]:
    if not isinstance(name, str) or not name.strip():
        return ["display_name は空でない文字列である必要があります"]
    if "<" in name or ">" in name:
        return ["display_name に HTML タグ (<, >) は使用できません"]
    return []


def _validate_model(model: Any) -> list[str]:
    if not isinstance(model, str) or not model.strip():
        return ["model は空でない文字列である必要があります"]
    return []


def _validate_personality(personality: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(personality, dict):
        return ["personality は辞書である必要があります"]
    traits = personality.get("traits")
    if not isinstance(traits, list) or not traits:
        errors.append("personality.traits は 1 件以上のリストである必要があります")
    else:
        for i, t in enumerate(traits):
            if not isinstance(t, str) or not t.strip():
                errors.append(f"personality.traits[{i}] は空でない文字列である必要があります")
    if not isinstance(personality.get("communication_style", ""), str):
        errors.append("personality.communication_style は文字列である必要があります")
    if not isinstance(personality.get("weakness", ""), str):
        errors.append("personality.weakness は文字列である必要があります")
    return errors


def _validate_string_list(items: Any, field_name: str) -> list[str]:
    if not isinstance(items, list) or not items:
        return [f"{field_name} は 1 件以上のリストである必要があります"]
    for i, v in enumerate(items):
        if not isinstance(v, str) or not v.strip():
            return [f"{field_name}[{i}] は空でない文字列である必要があります"]
    return []


def _validate_system_prompt(prompt: Any) -> list[str]:
    """system_prompt を検証する。

    プレースホルダ (`{orchestrator_instruction}` / `{feedback_context}`) は
    共通テンプレート (Layer 1) が付与するため、含まれていなくても許容する。
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return ["system_prompt は空でない文字列である必要があります"]
    if len(prompt) > SYSTEM_PROMPT_MAX_LENGTH:
        return [
            f"system_prompt は {SYSTEM_PROMPT_MAX_LENGTH} 文字以下である必要があります"
        ]
    return []


def _validate_optional_text(value: Any, field_name: str) -> list[str]:
    """description / perspective / tone 用の任意テキスト検証。"""
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        return [f"{field_name} は文字列である必要があります"]
    if len(value) > OPTIONAL_TEXT_MAX_LENGTH:
        return [
            f"{field_name} は {OPTIONAL_TEXT_MAX_LENGTH} 文字以下である必要があります"
        ]
    return []


def _validate_evaluation_criteria(criteria: Any) -> list[str]:
    if not isinstance(criteria, list):
        return ["evaluation_criteria はリストである必要があります"]
    if not (EVALUATION_CRITERIA_MIN <= len(criteria) <= EVALUATION_CRITERIA_MAX):
        return [
            f"evaluation_criteria は {EVALUATION_CRITERIA_MIN}〜"
            f"{EVALUATION_CRITERIA_MAX} 件である必要があります (現在 {len(criteria)} 件)"
        ]
    errors: list[str] = []
    for i, c in enumerate(criteria):
        if not isinstance(c, dict):
            errors.append(f"evaluation_criteria[{i}] は辞書である必要があります")
            continue
        if not isinstance(c.get("name"), str) or not c["name"].strip():
            errors.append(f"evaluation_criteria[{i}].name は空でない文字列である必要があります")
        if not isinstance(c.get("description"), str) or not c["description"].strip():
            errors.append(
                f"evaluation_criteria[{i}].description は空でない文字列である必要があります"
            )
    return errors


__all__ = [
    "RoleManager",
    "REQUIRED_FIELDS",
    "SYSTEM_PROMPT_PLACEHOLDERS",
    "SYSTEM_PROMPT_MAX_LENGTH",
    "ROLE_ID_PATTERN",
    "ROLE_ID_MIN_LENGTH",
    "ROLE_ID_MAX_LENGTH",
    "DEFAULT_ROLES",
    "PROTECTED_FIELDS_ON_UPDATE",
    "EVALUATION_CRITERIA_MIN",
    "EVALUATION_CRITERIA_MAX",
]
