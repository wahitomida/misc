# ===================================================================
#  Neo4j ヘッドレス起動スクリプト (CLI のみ・GUI 不要)
# -------------------------------------------------------------------
#  Neo4j Desktop が内部的に展開した Enterprise 5.24.0 と
#  バンドルされている Zulu JDK 17 をそのまま使い、
#  PowerShell から Neo4j サーバを直接起動します。
#
#  使い方:
#    .\start_neo4j_headless.ps1            # 起動
#    .\start_neo4j_headless.ps1 -Stop      # 停止
#    .\start_neo4j_headless.ps1 -Status    # 状態確認
#    .\start_neo4j_headless.ps1 -Reset     # データ削除 + 再初期化
# ===================================================================
param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$Reset,
    [string]$Password = 'eigyo-neo4j'
)

$ErrorActionPreference = 'Stop'

$Neo4jHome = 'C:\Users\hitomi\AppData\Local\Neo4j\Relate\Cache\dbmss\neo4j-enterprise-5.24.0'
$JavaHome  = 'C:\Users\hitomi\AppData\Local\Neo4j\Relate\Cache\runtime\zulu17.34.19-ca-jdk17.0.3-win_x64'

function Test-BoltPort {
    try {
        $r = Test-NetConnection -ComputerName 'localhost' -Port 7687 -InformationLevel Quiet -WarningAction SilentlyContinue
        return [bool]$r
    } catch {
        return $false
    }
}

function Show-Status {
    Write-Host "NEO4J_HOME : $Neo4jHome"
    Write-Host "JAVA_HOME  : $JavaHome"
    if (Test-Path $Neo4jHome) { Write-Host '  [OK] Neo4j install found' } else { Write-Host '  [NG] Neo4j install missing'; return }
    if (Test-Path $JavaHome)  { Write-Host '  [OK] JDK 17 found' }       else { Write-Host '  [NG] JDK 17 missing' }
    Write-Host ''
    Write-Host '--- Java/Neo4j プロセス ---'
    Get-Process -Name 'java','neo4j' -ErrorAction SilentlyContinue |
        Format-Table Id, ProcessName, StartTime, @{n='WS(MB)';e={[int]($_.WorkingSet64/1MB)}} -AutoSize
    Write-Host '--- Bolt (7687) 接続テスト ---'
    if (Test-BoltPort) { Write-Host '  [OK] localhost:7687 LISTENING' } else { Write-Host '  [--] localhost:7687 not listening' }
}

function Stop-Neo4j {
    Write-Host '[stop] running Java processes for Neo4j ...'
    $env:JAVA_HOME = $JavaHome
    $env:NEO4J_HOME = $Neo4jHome
    & "$Neo4jHome\bin\neo4j.bat" stop 2>&1 | Out-Host
    Start-Sleep -Seconds 2
    Get-Process -Name 'java' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "$JavaHome*" } |
        ForEach-Object { Write-Host "  killing PID $($_.Id)"; Stop-Process -Id $_.Id -Force }
    Write-Host '[stop] done.'
}

function Reset-Data {
    $dataDir = Join-Path $Neo4jHome 'data\databases'
    $txDir   = Join-Path $Neo4jHome 'data\transactions'
    if (Test-Path $dataDir) { Write-Host "[reset] removing $dataDir"; Remove-Item -Recurse -Force $dataDir }
    if (Test-Path $txDir)   { Write-Host "[reset] removing $txDir";   Remove-Item -Recurse -Force $txDir }
}

function Start-Neo4j {
    if (-not (Test-Path $Neo4jHome)) { throw "Neo4j install not found: $Neo4jHome" }
    if (-not (Test-Path $JavaHome))  { throw "JDK not found: $JavaHome" }

    $env:JAVA_HOME  = $JavaHome
    $env:NEO4J_HOME = $Neo4jHome
    $env:Path       = "$JavaHome\bin;$env:Path"

    if (Test-BoltPort) {
        Write-Host '[start] Bolt 7687 already listening - Neo4j is up.'
        return
    }

    Write-Host '[start] accepting evaluation license...'
    & "$Neo4jHome\bin\neo4j-admin.bat" server license --accept-evaluation 2>&1 | Out-Host

    Write-Host "[start] setting initial password for user neo4j..."
    & "$Neo4jHome\bin\neo4j-admin.bat" dbms set-initial-password $Password 2>&1 | Out-Host

    Write-Host '[start] launching Neo4j (background)...'
    $logDir = Join-Path $Neo4jHome 'logs'
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

    $stdout = Join-Path $logDir 'headless.out.log'
    $stderr = Join-Path $logDir 'headless.err.log'

    Start-Process -FilePath "$Neo4jHome\bin\neo4j.bat" `
        -ArgumentList 'console' `
        -WorkingDirectory $Neo4jHome `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError  $stderr | Out-Null

    Write-Host '[start] waiting for Bolt 7687...'
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if (Test-BoltPort) {
            Write-Host "[start] OK - Bolt is listening on 7687."
            Write-Host ""
            Write-Host "  URI      : bolt://localhost:7687"
            Write-Host "  USER     : neo4j"
            Write-Host "  PASSWORD : $Password"
            Write-Host ""
            Write-Host "logs:"
            Write-Host "  stdout = $stdout"
            Write-Host "  stderr = $stderr"
            return
        }
        Start-Sleep -Seconds 2
    }
    Write-Warning "Bolt did not become available within 120s. Check $stdout / $stderr"
}

if ($Stop)         { Stop-Neo4j;  return }
if ($Status)       { Show-Status; return }
if ($Reset)        { Stop-Neo4j; Reset-Data }

Start-Neo4j
Show-Status
