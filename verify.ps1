# Run full verification and save evidence (Windows)
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path "evidence" | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path "evidence" "verify-$stamp.log"

py -3 verify.py 2>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE

Write-Host "[verify] log: $log"
exit $code
