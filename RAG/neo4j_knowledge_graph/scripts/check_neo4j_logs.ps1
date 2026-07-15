$base = 'C:\Users\hitomi\AppData\Local\Neo4j\Relate\Cache\dbmss\neo4j-enterprise-5.24.0\logs'
foreach ($name in @('headless.err.log','headless.out.log','neo4j.log','debug.log')) {
    $p = Join-Path $base $name
    Write-Host "=================================================="
    Write-Host "  $p"
    Write-Host "=================================================="
    if (Test-Path $p) {
        Get-Content -Path $p -Tail 80 -ErrorAction SilentlyContinue
    } else {
        Write-Host '(missing)'
    }
}

Write-Host ''
Write-Host "=== java processes ==="
Get-Process -Name 'java' -ErrorAction SilentlyContinue |
    Format-Table Id, ProcessName, StartTime, Path -AutoSize

Write-Host "=== bolt port ==="
$r = Test-NetConnection -ComputerName 'localhost' -Port 7687 -InformationLevel Quiet -WarningAction SilentlyContinue
Write-Host "TcpTestSucceeded = $r"
