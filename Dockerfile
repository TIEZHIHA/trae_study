FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDQA_DB_PATH=/data/medqa.db

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV MEDQA_HOST=0.0.0.0 \
    MEDQA_PORT=8000

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["sh", "docker-entrypoint.sh"]
