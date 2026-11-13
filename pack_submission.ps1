# 打包提交目录：dist/<编号>_<姓名>_<A|B>/
# 排除：.env、模型权重、数据库、备份包、缓存、dist 自身
param([string]$Out = "dist")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$meta = Get-Content (Join-Path $root "submission.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$name = "$($meta.id)_$($meta.name)_$($meta.scheme)"
$dst = Join-Path $root (Join-Path $Out $name)
$dst = [System.IO.Path]::GetFullPath($dst)
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
New-Item -ItemType Directory -Force -Path $dst | Out-Null

$skipDirs = @("__pycache__", ".git", "backups", "exports", "dist", ".pytest_cache")
$skipExt = @(".pt", ".db", ".db-wal", ".db-shm", ".pyc", ".zip", ".tar", ".gz")
$skipFiles = @(".env", ".env.local", ".server.pid", "medqa.db")

$files = Get-ChildItem -Path $root -Recurse -File | Where-Object {
    $rel = $_.FullName.Substring($root.Length).TrimStart('\')
    $parts = $rel -split '\\'
    $inSkip = $false
    foreach ($d in $skipDirs) { if ($parts -contains $d) { $inSkip = $true } }
    if ($rel -like "logs\server.log") { $inSkip = $true }
    if ($rel -like "data\inbox\crawled\*") { $inSkip = $true }
    (-not $inSkip) -and ($skipExt -notcontains $_.Extension.ToLower()) -and ($skipFiles -notcontains $_.Name)
}

foreach ($f in $files) {
    $rel = $f.FullName.Substring($root.Length).TrimStart('\')
    $target = Join-Path $dst $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item $f.FullName $target -Force
}

$zip = Join-Path (Join-Path $root $Out) "$name.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dst -DestinationPath $zip

Write-Host "[pack] dir : $dst"
Write-Host "[pack] zip : $zip"
Write-Host "[pack] files: $($files.Count)"
Write-Host "[pack] excluded: .env / *.pt / *.db / backups / exports"
