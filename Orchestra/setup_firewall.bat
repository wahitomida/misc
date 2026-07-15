@echo off
chcp 65001 >nul
REM ==========================================
REM Windows ファイアウォール ポート 8080 開放
REM AI Orchestra Web UI を LAN/VPN 経由で公開するために必要
REM ※ 管理者権限で実行してください
REM ==========================================

echo.
echo Windows Firewall にポート 8080 の受信許可ルールを追加します。
echo ※ 管理者として実行する必要があります。
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 管理者権限がありません。右クリック→「管理者として実行」してください。
    pause
    exit /b 1
)

REM 既存ルールがあれば削除して再作成 (プロファイル変更等に追従するため)
netsh advfirewall firewall delete rule name="AI-Orchestra-Server" >nul 2>&1

netsh advfirewall firewall add rule ^
    name="AI-Orchestra-Server" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=8080 ^
    profile=domain,private ^
    description="AI Orchestra Web UI (FastAPI uvicorn)"

if errorlevel 1 (
    echo.
    echo [ERROR] ルール追加に失敗しました。
    pause
    exit /b 1
)

echo.
echo [OK] ファイアウォールルールを追加しました。
echo     ルール名:     AI-Orchestra-Server
echo     ポート:       8080/TCP
echo     プロファイル: ドメイン, プライベート
echo.
echo serve.bat で LAN/VPN 公開モードで起動できます。
pause
