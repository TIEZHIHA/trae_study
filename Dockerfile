FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=5 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_EXTRA_INDEX_URL=https://mirrors.aliyun.com/pytorch-wheels/cpu \
    MEDQA_DB_PATH=/data/medqa.db

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
# torch 使用 CPU 版轮子（体积约为 CUDA 版的 1/3），来自阿里云 pytorch-wheels 镜像
RUN pip install --no-cache-dir "torch==2.6.0+cpu" \
        --find-links https://mirrors.aliyun.com/pytorch-wheels/cpu \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MEDQA_HOST=0.0.0.0 \
    MEDQA_PORT=8000

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["sh", "docker-entrypoint.sh"]
