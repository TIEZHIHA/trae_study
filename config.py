# -*- coding: utf-8 -*-
"""
配置中心：所有模块只从这里读取配置，禁止在代码里散落连接串与路径。
支持环境变量覆盖，便于容器化与双平台部署（见 .env.example）。
本方案使用 SQLite 替代 Docker 里的 MongoDB/Neo4j。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name, default=False):
    """环境变量布尔解析：1/true/yes/on 为正，其余为负。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


# 数据库文件（SQLite 单文件，等价于 MongoDB+Neo4j 的存储层）
DB_PATH = Path(os.getenv("MEDQA_DB_PATH", str(BASE_DIR / "medqa.db")))

# 模型与词典路径
MODEL_PATH = BASE_DIR / "models" / "medical_ner_cls" / "best_model.pt"
METRICS_PATH = BASE_DIR / "models" / "medical_ner_cls" / "metrics.jsonl"
CURVE_PATH = BASE_DIR / "models" / "medical_ner_cls" / "curves.png"
DICT_PATH = BASE_DIR / "resource" / "dict" / "entity_dict.json"
BASE_WORDS_PATH = BASE_DIR / "resource" / "dict" / "base_words.txt"
ASSET_DIR = BASE_DIR / "resource"
TRAIN_DIR = BASE_DIR / "data" / "train"

# 是否启用训练好的模型（不可用时自动回退规则）
ENABLE_MODEL = _env_bool("ENABLE_MODEL", True)

# 置信度阈值：低于该值的识别结果走“低置信度澄清”兜底
CONF_THRESHOLD = 0.75

# 演示服务监听地址与端口
HOST = os.getenv("MEDQA_HOST", "0.0.0.0")
PORT = _env_int("MEDQA_PORT", 8000)

# 知识库自动同步间隔（分钟）与审核开关
KB_SYNC_INTERVAL_MIN = _env_int("KB_SYNC_INTERVAL_MIN", 10)
KB_REQUIRE_REVIEW = _env_bool("KB_REQUIRE_REVIEW", False)

# 备份：默认每天 BACKUP_CRON_HOUR 点执行，默认只打包不推送
BACKUP_CRON_HOUR = _env_int("BACKUP_CRON_HOUR", 3)
BACKUP_DRY_RUN = _env_bool("BACKUP_DRY_RUN", True)
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# 数据目录
INBOX_DIR = BASE_DIR / "data" / "inbox"
CRAWL_SAMPLE_DIR = BASE_DIR / "data" / "crawl_samples"
CORPUS_DIR = BASE_DIR / "data" / "corpus"
LOGS_DIR = BASE_DIR / "logs"
EVIDENCE_DIR = BASE_DIR / "evidence"

# 确保目录存在
for _d in (INBOX_DIR, CRAWL_SAMPLE_DIR, CORPUS_DIR, LOGS_DIR, EVIDENCE_DIR,
           MODEL_PATH.parent, DICT_PATH.parent, TRAIN_DIR):
    _d.mkdir(parents=True, exist_ok=True)
