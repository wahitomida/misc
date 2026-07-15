"""KotoBuddy 実 API に接続して IdeaDiscussion の最小フローを検証する E2E テスト。

実行例:
    pytest tests/e2e/test_idea_mini.py -v -s -m e2e

前提:
    Orchestra/.env に AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_KEY /
    KOTOBUDDY_MODE=azure が設定されていること。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cli_runner import build_idea_discussion
from core.config_loader import Settings

ORCHESTRA_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ORCHESTRA_DIR / "config"

EXPECTED_OUTPUTS = (
    "session_meta.json",
    "discussion.json",
    "full_conversation.md",
    "report.md",
    "evaluation.md",
    "summary.txt",
)


@pytest.mark.e2e
async def test_idea_mini_real_api(tmp_path: Path) -> None:
    """KotoBuddy 実機呼び出しで IdeaDiscussion の最小フローを確認する。

    成功条件:
        - Phase 1 で 2 体以上のエージェントが選定される
          (具体的な role_id は LLM 任せにし、テストでは指定しない)
        - セッションディレクトリ配下に 6 つの想定成果物が生成される
    """
    logging.basicConfig(level=logging.INFO, force=True)

    settings = Settings.load(config_dir=CONFIG_DIR)
    if not settings.api_key:
        pytest.skip("AZURE_OPENAI_KEY が .env に設定されていません")

    feature = build_idea_discussion(settings, no_confirm=True)

    output_dir = tmp_path / "output"
    session_dir = await feature.run(
        user_input="1+1=2の証明方法について議論して",
        planner_model="gpt-4.1",
        conductor_model="gpt-4.1-mini",
        synth_model="gpt-4.1",
        time_limit=180.0,
        max_agents=2,
        expertise="intermediate",
        output_dir=output_dir,
    )

    assert session_dir is not None, "session_dir is None (Phase 1 で拒否?)"
    assert session_dir.exists(), f"session_dir 不在: {session_dir}"

    # 6 ファイル全てが生成されていること
    print(f"\n[e2e] session_dir = {session_dir}")
    missing = [n for n in EXPECTED_OUTPUTS if not (session_dir / n).exists()]
    assert not missing, f"未生成ファイル: {missing}"

    for name in EXPECTED_OUTPUTS:
        path = session_dir / name
        size = path.stat().st_size
        print(f"[e2e] {name}: {size} bytes")
        assert size > 0, f"{name} が空ファイル"

    # 参加エージェント数チェック (session_meta.json から検証)
    import json as _json
    meta = _json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    agents = (
        meta.get("agents_used")
        or meta.get("selected_agents")
        or meta.get("agents")
        or []
    )
    assert len(agents) >= 2, f"参加エージェントが 2 体未満: {agents}"
