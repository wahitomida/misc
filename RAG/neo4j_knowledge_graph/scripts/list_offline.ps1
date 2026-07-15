$root = "C:\Users\hitomi\AppData\Local\Programs\Neo4j Desktop\resources\offline"
Write-Host "=== Listing $root ==="
Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $size = [math]::Round($_.Length / 1MB, 1)
    Write-Host ("{0,8} MB  {1}" -f $size, $_.FullName)
}
