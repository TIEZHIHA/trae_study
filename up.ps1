# One-click start (Windows): local mode by default, -Docker for containers
param([switch]$Docker)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Wait-Health([int]$tries = 40) {
    for ($i = 0; $i -lt $tries; $i++) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
            if ($r.status -eq "ok") {
                Write-Host "[up] ready nodes=$($r.components.graph.nodes) questions=$($r.questions)"
                return $true
            }
        } catch { Start-Sleep -Seconds 1 }
    }
    Write-Host "[up] health check timeout"
    return $false
}

if ($Docker) {
    Write-Host "[up] docker compose up -d --wait"
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { Write-Host "[up] docker compose failed"; exit 1 }
    if (-not (Wait-Health 90)) { exit 1 }
} else {
    py -3 -c "import fastapi, uvicorn, torch" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[up] installing dependencies"
        py -3 -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { exit 1 }
    }
    if (-not (Test-Path "models\medical_ner_cls\best_model.pt")) {
        Write-Host "[up] model missing, training first (~1 min)"
        py -3 -m models.train --ner-epochs 12 --intent-epochs 10
        if ($LASTEXITCODE -ne 0) { Write-Host "[up] training failed, fallback to rules" }
    }
    $proc = Start-Process -FilePath "py" -ArgumentList "-3", "GUI.py" `
        -WorkingDirectory $root -PassThru -WindowStyle Hidden
    Write-Host "[up] GUI.py PID=$($proc.Id)"
    if (-not (Wait-Health)) { exit 1 }
}

Write-Host "[up] OK  http://127.0.0.1:8000"
exit 0
