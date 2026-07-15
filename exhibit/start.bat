@echo off
chcp 65001 >nul
REM ExhibiReport - ローカル起動 (127.0.0.1:8005)
cd /d "%~dp0"
python run_local.py %*
pause
