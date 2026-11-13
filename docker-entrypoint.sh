#!/usr/bin/env sh
# 容器入口：初始化图谱 -> 模型缺失则训练 -> 启动服务
set -e
export PYTHONUNBUFFERED=1

python -c "import storage; from kb import auto_add; storage.init_db(); auto_add.sync_once()"

if [ ! -f "models/medical_ner_cls/best_model.pt" ]; then
  echo "[entrypoint] 未发现模型，开始训练（CPU）"
  python -m models.train --ner-epochs 12 --intent-epochs 10 || \
    echo "[entrypoint] 训练失败，回退规则版"
fi

exec python GUI.py
