$env:PYTHONIOENCODING = 'utf-8'

$root    = 'C:\Users\hitomi\source\eigyo\RAG\neo4j_knowledge_graph'
$logDir  = Join-Path $root 'output'
$logPath = Join-Path $logDir ('pipeline_run_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

Write-Host "log file = $logPath"
Write-Host ''

Set-Location 'C:\Users\hitomi\source\eigyo\RAG'

& 'C:\Users\hitomi\source\eigyo\venv\Scripts\python.exe' -u `
    -m neo4j_knowledge_graph.main `
    --input '..\workdir_v6\05_analysis.csv' `
    --clear-graph `
    --log-file $logPath

Write-Host ''
Write-Host "exit code = $LASTEXITCODE"
Write-Host "log file  = $logPath"
