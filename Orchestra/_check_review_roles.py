"""_build_meeting_plan がカスタムロールを合流させるか確認する。"""

from __future__ import annotations

import sys
from pathlib import Path


LOG_PATH = Path(__file__).with_suffix(".log")


def _log(msg: str) -> None:
    LOG_PATH.open("a", encoding="utf-8").write(msg + "\n")


def main() -> None:
    # 実行ごとにログをリセット
    LOG_PATH.write_text("", encoding="utf-8")

    from core.data_models import ScanResult
    from core.role_manager import RoleManager
    from features.code_review.meeting import _build_meeting_plan

    rm = RoleManager(Path("config/roles"))

    # カスタムロール一時作成 (直接 YAML 書き出し)
    custom_path = rm.roles_dir / "custom_meeting_test.yaml"
    import yaml

    custom_role = {
        "role_id": "custom_meeting_test",
        "display_name": "🧪 会議テスト",
        "model": "gpt-4.1",
        "default_level": "medium",
        "description": "会議参加テスト用のカスタムロール",
        "personality": {"traits": ["テスト"], "communication_style": "", "weakness": ""},
        "expertise": ["testing"],
        "domain_tags": ["test"],
        "evaluation_criteria": [
            {"name": "参加度", "description": "会議に貢献できるか"},
            {"name": "独自性", "description": "独自視点があるか"},
            {"name": "共感性", "description": "他者に反応できるか"},
        ],
        "system_prompt": "あなたはテスト用のロールです。会議で発言してください。",
    }
    with custom_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            custom_role, f, allow_unicode=True, sort_keys=False, default_flow_style=False,
        )
    rm.refresh_cache()

    try:
        scan_result = ScanResult(
            target_path=Path("dummy"),
            total_files=0,
            total_lines=100,
        )
        findings = {
            "algorithm": [{"title": "test"}],
            "readability": [{"title": "test"}],
        }

        plan_default = _build_meeting_plan(scan_result, findings, focus="all")
        default_ids = [a.role_id for a in plan_default.selected_agents]
        _log(f"role_manager 無し: {default_ids}")

        plan_ext = _build_meeting_plan(
            scan_result, findings, focus="all", role_manager=rm
        )
        ext_ids = [a.role_id for a in plan_ext.selected_agents]
        _log(f"role_manager 有り: {ext_ids}")

        assert "custom_meeting_test" in ext_ids, "カスタムロールが合流していない"
        assert "custom_meeting_test" not in default_ids, "role_manager なしで混入している"
        _log("OK: カスタムロールが Review 会議に合流される")
    except Exception as e:  # noqa: BLE001
        _log(f"NG: {type(e).__name__}: {e}")
        raise
    finally:
        if custom_path.exists():
            custom_path.unlink()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

