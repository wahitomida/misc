Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "killing PID $($_.Id) (Path=$($_.Path))"
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 2
$remaining = Get-Process python -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Host 'still alive:'
    $remaining | Format-Table Id, Path -AutoSize
} else {
    Write-Host 'all python processes terminated.'
}
