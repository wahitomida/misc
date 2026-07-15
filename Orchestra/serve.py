"""AI Orchestra Web UI 起動スクリプト。

使用例:
    python serve.py                                     # デフォルト (0.0.0.0:8080)
    python serve.py --host 127.0.0.1                    # ローカルのみ
    python serve.py --port 9000 --reload                # 開発モード (別ポート)
    python serve.py --debug                             # デバッグログ + CORS + Swagger UI

LAN/VPN 経由で他デバイスから接続:
    1. 初回のみ setup_firewall.bat を管理者権限で実行 (Windows ファイアウォール開放)
    2. python serve.py --host 0.0.0.0 --port 8080
    3. 表示された URL (http://<LAN/VPN IP>:8080/) を接続元に共有
"""

from __future__ import annotations

import os
import socket
import sys

import typer
import uvicorn

# Windows の cp932 stdout だと絵文字で UnicodeEncodeError になるため UTF-8 化
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

app = typer.Typer(
    help="🎵 AI Orchestra Web UI",
    add_completion=False,
)


def _lan_ipv4() -> list[str]:
    """ホストの非ループバック IPv4 アドレスを列挙する。

    LAN の IP (192.168.x.x など) + VPN の IP (10.x.x.x など) が
    まとめて取れる。取得不能時は空リスト。
    """
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip and not ip.startswith("127.") and ip not in ips:
            ips.append(ip)
    return ips


def _classify_ip(ip: str) -> str:
    """IP アドレスの種類を人間可読なラベルに変換する。"""
    if ip.startswith("192.168.") or ip.startswith("172."):
        return "LAN"
    if ip.startswith("10."):
        return "VPN/LAN"
    if ip.startswith("169.254."):
        return "APIPA"
    return "Network"


def _print_access_urls(host: str, port: int, *, debug: bool) -> None:
    """起動直後に接続可能な URL を一覧表示する。"""
    print("=" * 60)
    print(f" 🎵 AI Orchestra — Web UI  (port {port})")
    print("=" * 60)

    if host == "0.0.0.0":
        # 全インターフェース待受: ローカル + LAN/VPN 全て表示
        print(f"   Local     : http://localhost:{port}/")
        print(f"   Local (IP): http://127.0.0.1:{port}/")
        for ip in _lan_ipv4():
            label = _classify_ip(ip)
            print(f"   {label:<10}: http://{ip}:{port}/")
    elif host in ("127.0.0.1", "localhost"):
        print(f"   Local     : http://localhost:{port}/")
        print(f"   Local (IP): http://127.0.0.1:{port}/")
    else:
        print(f"   Bound     : http://{host}:{port}/")

    if debug:
        print("-" * 60)
        print(f"   Swagger   : http://localhost:{port}/api/docs")
        print(f"   Health    : http://localhost:{port}/api/health")
    print("=" * 60)
    print(" Ctrl+C で停止します")
    print()


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", "-p", help="ポート番号"),
    host: str = typer.Option(
        "127.0.0.1", "--host",
        help="バインドアドレス (127.0.0.1=ローカルのみ, 0.0.0.0=LAN/VPN公開)",
    ),
    lan: bool = typer.Option(
        False, "--lan", "-l",
        help="LAN/VPN 公開 (--host 0.0.0.0 のショートカット)",
    ),
    reload: bool = typer.Option(False, "--reload", "-r", help="ファイル変更で自動リロード"),
    debug: bool = typer.Option(False, "--debug", "-d", help="デバッグログ + CORS + Swagger UI (/api/docs)"),
) -> None:
    """AI Orchestra Web UI を起動する。

    例:
        python serve.py                       # ローカルのみ (127.0.0.1:8080)
        python serve.py --lan                 # LAN/VPN 公開
        python serve.py --lan --reload --debug  # 開発モード
    """
    # --lan は --host 0.0.0.0 のエイリアス。両方指定された場合は --lan を優先。
    if lan:
        host = "0.0.0.0"

    # web.app の create_app() に debug フラグを伝える (uvicorn.run は
    # 文字列インポートなので引数直接には渡せない)
    if debug:
        os.environ["ORCHESTRA_DEBUG"] = "1"

    # 接続可能な URL を先に表示 (uvicorn.run はブロックするため)
    _print_access_urls(host, port, debug=debug)

    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="debug" if debug else "info",
    )


if __name__ == "__main__":
    app()
