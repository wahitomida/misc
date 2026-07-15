@echo off
chcp 65001 >nul
REM ExhibiReport - LAN/VPN 公開モード (0.0.0.0:8005)
REM
REM 初回のみ管理者として setup_firewall.bat を実行してください。
REM 表示される LAN/VPN URL を他メンバーに共有します。
cd /d "%~dp0"
python run_local.py --lan %*
pause
