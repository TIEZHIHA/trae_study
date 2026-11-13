#!/usr/bin/env bash
# 运行全量验证并落盘证据（macOS / Linux）
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p evidence
log="evidence/verify-$(date +%Y%m%d-%H%M%S).log"

python3 verify.py 2>&1 | tee "$log"
code=${PIPESTATUS[0]}

echo "[verify] 日志：$log"
exit "$code"
