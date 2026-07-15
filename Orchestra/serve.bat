@echo off
chcp 65001 >nul
REM ==========================================
REM AI Orchestra - LAN/VPN 公開モード起動
REM
REM 初回のみ管理者として setup_firewall.bat を実行してください。
REM 起動時に表示される LAN/VPN URL を他メンバーに共有します。
REM
REM 追加引数はそのまま serve.py に渡されます。
REM   例: serve.bat --debug          -> 開発モードで起動
REM   例: serve.bat --port 9000      -> 別ポートで起動
REM ==========================================
cd /d "%~dp0"
python serve.py --host 0.0.0.0 --port 8080 --reload %*
pause
