# 一键准备 Docker 环境（需管理员权限；完成后必须重启）
# 用法：右键“以管理员身份运行 PowerShell”，执行
#   powershell -ExecutionPolicy Bypass -File .\setup_docker.ps1
$ErrorActionPreference = "Stop"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "[setup] 需要管理员权限，请右键 PowerShell 选择“以管理员身份运行”"
    exit 1
}

Write-Host "[setup] 1/2 启用 WSL2（含虚拟机平台）"
wsl --install --no-distribution
if ($LASTEXITCODE -ne 0) {
    Write-Host "[setup] WSL 安装返回 $LASTEXITCODE，可能已安装或需要手动处理"
}

Write-Host "[setup] 2/2 安装 Docker Desktop"
winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements

Write-Host ""
Write-Host "[setup] 安装已提交。请重启电脑，然后执行："
Write-Host "        .\up.ps1 -Docker"
Write-Host "        .\verify.ps1"
Write-Host "[setup] 重启前 Docker 无法启动，属于正常现象。"
