"""AI Orchestra CLI (Phase G-5)。

エントリポイント:
    - ``idea``       — 機能①: 技術議論 (``features.idea_discussion.IdeaDiscussion``)
    - ``review``     — 機能②: コードレビュー (``features.code_review.CodeReview``)
    - ``list-roles`` — 利用可能ロールの一覧
    - ``history``    — セッション履歴
    - ``replay``     — 過去セッション再表示
    - ``role-stats`` — ロール別統計

設計書: ``doc/16_cli_interface.md`` §16.1, §16.2
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Windows の cp932 stdout だと絵文字で UnicodeEncodeError になるため UTF-8 化
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

import typer
import yaml
from rich.console import Console
from rich.table import Table

from cli_runner import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_OUTPUT_DIR,
    HISTORY_DEFAULT_LIMIT,
    REPLAY_SECTIONS,
    SCRIPT_DIR,
    SECTION_TO_FILENAME,
    build_idea_discussion,
    build_code_review,
    configure_logging,
    load_settings,
    print_error_and_exit,
)
from display.progress_display import PhaseProgress

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    help="🎼 AI Orchestra — 研究者のためのAI議論ツール",
    add_completion=False,
    no_args_is_help=True,
)


# ----------------------------------------------------------------------
# idea コマンド
# ----------------------------------------------------------------------


@app.command()
def idea(
    prompt: str = typer.Argument(..., help="議論したいテーマ・質問"),
    # モデル指定
    planner_model: str = typer.Option(
        "gpt-5.4", "--planner-model", help="Phase 1 計画立案モデル"
    ),
    conductor_model: str = typer.Option(
        "gpt-4.1", "--conductor-model", help="Phase 2 進行管理モデル"
    ),
    synth_model: str = typer.Option(
        "gpt-5.4", "--synth-model", help="Phase 3 統合モデル"
    ),
    # 制御パラメータ
    time_limit: int = typer.Option(
        300, "--time-limit", "-t", help="制限時間（秒）"
    ),
    max_agents: int = typer.Option(
        5, "--max-agents", "-n", help="最大参加AI数"
    ),
    expertise: str = typer.Option(
        "intermediate",
        "--expertise",
        "-e",
        help="beginner/intermediate/expert",
    ),
    # follow-up
    follow_up: Optional[str] = typer.Option(
        None, "--follow-up", "-f", help="継続するセッションID"
    ),
    attach: Optional[list[Path]] = typer.Option(
        None, "--attach", "-a", help="添付ファイル（複数指定可）"
    ),
    focus_hypothesis: Optional[list[str]] = typer.Option(
        None,
        "--focus-hypothesis",
        help="フォーカスする仮説ID（複数指定可）",
    ),
    # 出力
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", "-o", help="出力ディレクトリ"
    ),
    # 共通フラグ
    no_confirm: bool = typer.Option(
        False, "--no-confirm", help="実行確認をスキップ"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="詳細ログ表示"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="進捗表示を最小化"
    ),
) -> None:
    """💡 技術テーマについてAIが多角的に議論し、洞察・仮説・実験計画を導出する."""
    configure_logging(verbose=verbose, quiet=quiet)
    if not verbose:
        logging.getLogger().setLevel(logging.ERROR)
    settings = load_settings()
    feature = build_idea_discussion(settings, no_confirm=no_confirm)

    progress = PhaseProgress(total_phases=4, console=console)
    try:
        with progress:
            output_path = asyncio.run(
                feature.run(
                    user_input=prompt,
                    planner_model=planner_model,
                    conductor_model=conductor_model,
                    synth_model=synth_model,
                    time_limit=float(time_limit),
                    max_agents=max_agents,
                    expertise=expertise,
                    follow_up_id=follow_up,
                    attached_files=attach,
                    focus_hypotheses=focus_hypothesis,
                    output_dir=output_dir,
                    on_phase=progress.advance,
                )
            )
            progress.complete()
    except Exception as e:  # noqa: BLE001 - CLI トップで表示して終了
        print_error_and_exit(e)
        return

    if output_path is None:
        console.print("[yellow]⚠ 議論はキャンセルされました[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"\n✅ 出力: [link]{output_path}[/link]")


# ----------------------------------------------------------------------
# review コマンド
# ----------------------------------------------------------------------


@app.command()
def review(
    target: Path = typer.Argument(..., help="レビュー対象のディレクトリ"),
    # モデル指定
    planner_model: str = typer.Option("gpt-5.4", "--planner-model"),
    conductor_model: str = typer.Option("gpt-4.1", "--conductor-model"),
    synth_model: str = typer.Option(
        "gpt-5.4", "--synth-model"
    ),
    # 制御パラメータ
    time_limit: int = typer.Option(
        600,
        "--time-limit",
        "-t",
        help="制限時間（秒）。デフォルト10分",
    ),
    max_agents: int = typer.Option(6, "--max-agents", "-n"),
    focus: str = typer.Option(
        "all",
        "--focus",
        help="重点モード: all/pre_submission/performance/structure/handover/algorithm",
    ),
    ignore: Optional[str] = typer.Option(
        None,
        "--ignore",
        help="追加ignoreパターン（カンマ区切り）",
    ),
    # 出力
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", "-o"
    ),
    # 共通フラグ
    no_confirm: bool = typer.Option(
        False, "--no-confirm", help="実行確認をスキップ"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="詳細ログ表示"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="進捗表示を最小化"
    ),
) -> None:
    """🔬 研究コードを6観点から多角的にレビューし、修正指示書を生成する."""
    del no_confirm  # review は内部で確認を出さない
    configure_logging(verbose=verbose, quiet=quiet)
    if not verbose:
        logging.getLogger().setLevel(logging.ERROR)
    settings = load_settings()
    feature = build_code_review(settings)

    ignore_patterns = (
        [p.strip() for p in ignore.split(",") if p.strip()]
        if ignore
        else None
    )

    progress = PhaseProgress(total_phases=5, console=console)
    try:
        with progress:
            output_path = asyncio.run(
                feature.run(
                    target_path=target,
                    focus=focus,
                    planner_model=planner_model,
                    conductor_model=conductor_model,
                    synth_model=synth_model,
                    time_limit=float(time_limit),
                    max_agents=max_agents,
                    ignore_patterns=ignore_patterns,
                    output_dir=output_dir,
                    on_phase=progress.advance,
                )
            )
            progress.complete()
    except Exception as e:  # noqa: BLE001
        print_error_and_exit(e)
        return

    if output_path is None:
        console.print(
            "[yellow]⚠ スキャン結果が空のため、レビューを中止しました[/yellow]"
        )
        raise typer.Exit(code=1)
    console.print(f"\n✅ 出力: [link]{output_path}[/link]")


# ----------------------------------------------------------------------
# list-roles コマンド
# ----------------------------------------------------------------------


@app.command("list-roles")
def list_roles(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="詳細表示"
    ),
) -> None:
    """📋 利用可能なロール一覧を表示."""
    from core.role_manager import RoleManager

    roles_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR / "roles"
    manager = RoleManager(roles_dir=roles_dir)
    summaries = manager.list_available_roles()

    console.print(f"\n📋 利用可能なロール ({len(summaries)}個)")
    console.print("━" * 50)

    if verbose:
        _print_roles_verbose(summaries, manager)
    else:
        _print_roles_table(summaries)


def _print_roles_table(summaries: list[dict[str, Any]]) -> None:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Role ID", style="cyan")
    table.add_column("Display", style="magenta")
    table.add_column("Model", style="yellow")
    table.add_column("Expertise", style="green")
    for s in summaries:
        expertise_str = ", ".join(s.get("expertise", [])[:4])
        table.add_row(
            s["role_id"],
            s["display_name"],
            s.get("model", ""),
            expertise_str,
        )
    console.print(table)


def _print_roles_verbose(
    summaries: list[dict[str, Any]],
    manager: Any,
) -> None:
    for s in summaries:
        role = manager.load_role(s["role_id"])
        personality = role.get("personality", {})
        feedback_stats = role.get("feedback_stats", {})
        console.print(f"\n[bold]{s['display_name']} ({s['role_id']})[/bold]")
        console.print(
            f"  モデル: {s.get('model', '')} | "
            f"level: {role.get('level', 'medium')}"
        )
        expertise = ", ".join(s.get("expertise", []))
        if expertise:
            console.print(f"  得意: {expertise}")
        domain = ", ".join(s.get("domain_tags", []))
        if domain:
            console.print(f"  分野: {domain}")
        thinking = personality.get("thinking_style", "")
        if thinking:
            console.print(f"  性格: {thinking}")
        weakness = personality.get("weakness", "")
        if weakness:
            console.print(f"  弱み: {weakness}")
        if feedback_stats:
            sessions = feedback_stats.get("total_sessions", 0)
            avg = feedback_stats.get("avg_peer_score", 0.0)
            trend = feedback_stats.get("trend", "insufficient_data")
            console.print(
                f"  統計: {sessions}セッション | 平均{avg}/5 | trend: {trend}"
            )


# ----------------------------------------------------------------------
# history コマンド
# ----------------------------------------------------------------------


@app.command()
def history(
    chain: Optional[str] = typer.Option(
        None, "--chain", "-c", help="指定セッションのチェーンを表示"
    ),
    limit: int = typer.Option(
        HISTORY_DEFAULT_LIMIT, "--limit", "-l", help="表示件数"
    ),
    type_filter: Optional[str] = typer.Option(
        None, "--type", help="idea/review でフィルタ"
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", "-o"
    ),
) -> None:
    """📜 過去のセッション一覧を表示."""
    sessions = _collect_sessions(output_dir)
    if not sessions:
        console.print(
            f"[dim]セッション履歴がありません ({output_dir})[/dim]"
        )
        return

    if chain:
        _print_chain(sessions, chain)
        return

    if type_filter:
        sessions = [s for s in sessions if s.get("type") == type_filter]

    sessions = sessions[:limit]
    _print_history_table(sessions, limit)


def _print_history_table(sessions: list[dict[str, Any]], limit: int) -> None:
    console.print(f"\n📜 セッション履歴 (直近{limit}件)")
    console.print("━" * 60)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("時間", style="yellow")
    table.add_column("品質", style="green")
    table.add_column("収束", style="green")
    table.add_column("テーマ", style="white")
    for s in sessions:
        chain_depth = s.get("follow_up", {}).get("chain_depth", 0)
        prefix = f"[F#{chain_depth}] " if chain_depth else ""
        topic = prefix + str(s.get("user_prompt_preview", ""))
        eval_summary = s.get("evaluation_summary") or {}
        table.add_row(
            s["session_id"],
            s.get("type", ""),
            _format_duration(s.get("duration_sec", 0)),
            f"{eval_summary.get('overall_quality', 0):.1f}",
            f"{s.get('final_convergence', 0):.2f}",
            topic[:40],
        )
    console.print(table)


def _print_chain(sessions: list[dict[str, Any]], session_id: str) -> None:
    target = next(
        (s for s in sessions if s["session_id"] == session_id), None
    )
    if target is None:
        console.print(
            f"[red]セッションが見つかりません: {session_id}[/red]"
        )
        raise typer.Exit(code=1)
    chain_ids: list[str] = target.get("follow_up", {}).get("chain") or [
        session_id
    ]
    console.print(f"\n🔗 Session Chain: {session_id}")
    console.print("━" * 40)
    by_id = {s["session_id"]: s for s in sessions}
    for i, cid in enumerate(chain_ids):
        s = by_id.get(cid)
        if s is None:
            console.print(f"  [dim]📍 {cid} (詳細なし)[/dim]")
            continue
        marker = "初回" if i == 0 else f"follow-up #{i}"
        topic = str(s.get("user_prompt_preview", ""))[:60]
        console.print(f"\n📍 {cid} [{marker}] — {topic}")


# ----------------------------------------------------------------------
# replay コマンド
# ----------------------------------------------------------------------


@app.command()
def replay(
    session_id: str = typer.Argument(..., help="再表示するセッションID"),
    section: str = typer.Option(
        "conversation",
        "--section",
        "-s",
        help=f"{'/'.join(REPLAY_SECTIONS)}",
    ),
    output_dir: Path = typer.Option(
        DEFAULT_OUTPUT_DIR, "--output-dir", "-o"
    ),
) -> None:
    """🔄 過去セッションの内容を再表示."""
    if section not in REPLAY_SECTIONS:
        console.print(
            f"[red]section は {'/'.join(REPLAY_SECTIONS)} のいずれか[/red]"
        )
        raise typer.Exit(code=1)
    session_dir = output_dir / session_id
    if not session_dir.exists():
        console.print(
            f"[red]セッションが見つかりません: {session_dir}[/red]"
        )
        raise typer.Exit(code=1)
    file_path = session_dir / SECTION_TO_FILENAME[section]
    if not file_path.exists():
        console.print(
            f"[red]ファイルが見つかりません: {file_path}[/red]"
        )
        raise typer.Exit(code=1)
    console.print(file_path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# role-stats コマンド
# ----------------------------------------------------------------------


@app.command("role-stats")
def role_stats(
    role_id: Optional[str] = typer.Argument(
        None, help="特定ロールの詳細。省略で全ロール"
    ),
) -> None:
    """📊 ロール別のパフォーマンス統計を表示."""
    roles_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR / "roles"
    if role_id:
        _show_role_detail(roles_dir, role_id)
    else:
        _show_role_overview(roles_dir)


def _show_role_overview(roles_dir: Path) -> None:
    console.print("\n📊 ロール別パフォーマンス統計")
    console.print("━" * 50)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Role", style="cyan")
    table.add_column("Sessions", style="yellow")
    table.add_column("Self", style="green")
    table.add_column("Peer", style="green")
    table.add_column("Trend", style="magenta")
    for yaml_path in sorted(roles_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        stats = data.get("feedback_stats", {}) or {}
        table.add_row(
            f"{data.get('display_name', '')} ({data.get('role_id', '')})",
            str(stats.get("total_sessions", 0)),
            f"{stats.get('avg_self_score', 0):.2f}",
            f"{stats.get('avg_peer_score', 0):.2f}",
            str(stats.get("trend", "insufficient_data")),
        )
    console.print(table)


def _show_role_detail(roles_dir: Path, role_id: str) -> None:
    yaml_path = roles_dir / f"{role_id}.yaml"
    if not yaml_path.exists():
        console.print(f"[red]ロールが見つかりません: {role_id}[/red]")
        raise typer.Exit(code=1)
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    stats = data.get("feedback_stats", {}) or {}
    history_entries = data.get("performance_history", []) or []
    console.print(
        f"\n📊 {data.get('display_name', '')} ({role_id}) — 詳細統計"
    )
    console.print("━" * 50)
    console.print(f"総セッション数: {stats.get('total_sessions', 0)}")
    console.print(
        f"平均自己評価: {stats.get('avg_self_score', 0):.2f} / 5.0"
    )
    console.print(
        f"平均他者評価: {stats.get('avg_peer_score', 0):.2f} / 5.0"
    )
    console.print(
        f"トレンド: {stats.get('trend', 'insufficient_data')}"
    )
    if history_entries:
        console.print("\n直近セッション:")
        for entry in history_entries[-5:]:
            date = entry.get("date", "?")
            topic = entry.get("topic", "")
            self_score = entry.get("self_score", "?")
            console.print(f"  {date} [{self_score}/5] {topic}")


# ----------------------------------------------------------------------
# ヘルパー: セッション収集
# ----------------------------------------------------------------------


def _collect_sessions(output_dir: Path) -> list[dict[str, Any]]:
    """``output_dir/*/session_meta.json`` を読み込み、新しい順に返す。"""
    if not output_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for session_dir in sorted(output_dir.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        meta_path = session_dir / "session_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sessions.append(meta)
    return sessions


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()
