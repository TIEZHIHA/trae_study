#!/usr/bin/env bash
# 一键启动（macOS / Linux）：./up.sh 或 ./up.sh --docker
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--docker" ]; then
  echo "[up] docker compose up -d --wait"
  docker compose up -d --wait
else
  if ! python3 -c "import fastapi, uvicorn, torch" 2>/dev/null; then
    echo "[up] 安装依赖"
    python3 -m pip install -r requirements.txt
  fi
  if [ ! -f "models/medical_ner_cls/best_model.pt" ]; then
    echo "[up] 未发现模型，先训练"
    python3 -m models.train --ner-epochs 12 --intent-epochs 10 || \
      echo "[up] 训练失败，将以规则版启动"
  fi
  mkdir -p logs
  nohup python3 GUI.py > logs/server.log 2>&1 &
  echo $! > .server.pid
  echo "[up] GUI.py PID=$(cat .server.pid)"
fi

for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "[up] 服务就绪 http://127.0.0.1:8000"
    exit 0
  fi
  sleep 1
done

echo "[up] 健康检查超时"
exit 1
