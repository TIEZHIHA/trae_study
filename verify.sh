#!/usr/bin/env bash
# 运行全量验证并落盘证据（macOS / Linux）
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p evidence
log="evidence/verify-$(date +%Y%m%d-%H%M%S).log"

# 先写入运行环境头：V5 跨平台判定依赖日志中出现 darwin
{
  echo "# 运行环境"
  echo "uname: $(uname -a)"
  echo "os: $(sw_vers 2>/dev/null | tr '\n' ' ' || cat /etc/os-release 2>/dev/null | head -2 | tr '\n' ' ')"
  echo "python: $(python3 -V 2>&1)"
  echo "time: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo
} | tee "$log"

python3 verify.py 2>&1 | tee -a "$log"
code=${PIPESTATUS[0]}

echo "[verify] 日志：$log"
exit "$code"
