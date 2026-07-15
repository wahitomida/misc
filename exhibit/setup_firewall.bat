@echo off
chcp 65001 >nul
REM ==========================================
REM Windows ファイアウォール ポート 8005 開放
REM ※ 管理者権限で実行してください
REM ==========================================

echo.
echo Windows Firewall にポート 8005 の受信許可ルールを追加します。
echo ※ 管理者として実行する必要があります。
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 管理者権限がありません。右クリック→「管理者として実行」してください。
    pause
    exit /b 1
)

REM 既存ルールがあれば削除して再作成
netsh advfirewall firewall delete rule name="ExhibiReport-Server" >nul 2>&1

netsh advfirewall firewall add rule ^
    name="ExhibiReport-Server" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=8005 ^
    profile=domain,private ^
    description="ExhibiReport 展示会調査レポート (FastAPI uvicorn)"

if errorlevel 1 (
    echo.
    echo [ERROR] ルール追加に失敗しました。
    pause
    exit /b 1
)

echo.
echo [OK] ファイアウォールルールを追加しました。
echo     ルール名: ExhibiReport-Server
echo     ポート:   8005/TCP
echo     プロファイル: ドメイン, プライベート
echo.
echo serve.bat で LAN 公開モードで起動できます。
pause
