#!/usr/bin/env python3
"""ExhibiReport ローカル起動スクリプト。

使い方:
    python run_local.py                  # ローカルのみ (127.0.0.1:8005)
    python run_local.py --lan            # LAN/VPN 公開 (0.0.0.0:8005)
    python run_local.py --lan --no-reload  # 本番想定
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 8005


def lan_ipv4() -> list[str]:
    """ホストの非ループバック IPv4 アドレスを列挙。"""
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


def run_backend(host: str, port: int, *, reload: bool) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn", "main:app",
           "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")

    print(f"[INFO] ExhibiReport 起動: http://{host}:{port}")
    if host == "0.0.0.0":
        print(f"       ローカル:  http://127.0.0.1:{port}/")
        for ip in lan_ipv4():
            print(f"       LAN/VPN:  http://{ip}:{port}/")
    return subprocess.Popen(cmd, cwd=str(APP_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(description="ExhibiReport 起動")
    parser.add_argument("--lan", action="store_true",
                        help="0.0.0.0 で待受 (LAN/VPN メンバーに公開)")
    parser.add_argument("--host", default=None,
                        help="バインドホスト（指定時は --lan より優先）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-reload", action="store_true",
                        help="--reload を無効化")
    args = parser.parse_args()

    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")

    try:
        from dotenv import load_dotenv
        load_dotenv(APP_DIR / ".env")
    except ImportError:
        print("[WARN] python-dotenv 未インストール。.env は読み込まれません。")

    procs: list[subprocess.Popen] = []
    try:
        procs.append(run_backend(
            host, args.port,
            reload=not args.no_reload,
        ))
        print("\n[INFO] Ctrl+C で停止します。")
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n[INFO] シャットダウン中...")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=5)


if __name__ == "__main__":
    main()
