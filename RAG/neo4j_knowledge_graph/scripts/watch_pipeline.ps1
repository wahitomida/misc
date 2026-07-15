$path = 'C:\Users\hitomi\source\eigyo\RAG\neo4j_knowledge_graph\output\pipeline_run.log'
$a = (Get-Item $path).Length
Start-Sleep -Seconds 10
$b = (Get-Item $path).Length
Write-Host "size_before=$a size_after=$b delta=$($b - $a) bytes/10s"

Write-Host ''
Write-Host '--- last 30 INFO/WARN/ERROR lines ---'
Get-Content $path -Encoding Unicode |
    Select-String -Pattern 'INFO|ERROR|WARN|エラー' -CaseSensitive:$false |
    Select-Object -Last 30 |
    ForEach-Object { $_.Line }

Write-Host ''
Write-Host '--- python processes ---'
Get-Process python -ErrorAction SilentlyContinue |
    Format-Table Id, StartTime, @{n='WS_MB'; e={[int]($_.WorkingSet64 / 1MB)}}, Path -AutoSize
