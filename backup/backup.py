# -*- coding: utf-8 -*-
"""
GitHub 定时备份（方案 D5）：
  快照导出 -> 敏感扫描 -> 命中即中止 -> 打包 ->（DRY_RUN=false 时）推送

默认 BACKUP_DRY_RUN=true，只出包不推送；凭据只从环境变量读取，不落仓库。
未装 git / 未配置仓库时自动退化为本地打包，不阻塞演示。
"""
import csv
import json
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

import config
import storage
from backup.sensitive import scan_files

BACKUP_DIR = config.BASE_DIR / "backups"
EXPORT_DIR = config.BASE_DIR / "exports"
STATUS_FILE = config.LOGS_DIR / "backup-status.json"
REPORT_FILE = config.EVIDENCE_DIR / "backup-report.txt"

# 纳入备份的范围
INCLUDE_DIRS = ["kb", "backup", "web", "mobile", "docs", "resource",
                "data/inbox", "data/train", "data/crawl_samples", "logs", "exports"]
INCLUDE_FILES = [
    "config.py", "schema.py", "storage.py", "clean.py", "segment.py",
    "build_graph.py", "crawler.py", "resources.py", "runtime.py",
    "qa_service.py", "GUI.py", "verify.py", "selfcheck.py",
    "requirements.txt", "README.md", "NOTES.md", "submission.json",
    ".env.example", "docker-compose.yml", "Dockerfile",
    "up.ps1", "up.sh", "verify.ps1", "verify.sh", "setup_docker.ps1",
    "pack_submission.ps1", "MEMORY.md",
]

# 排除：密钥、模型权重、数据库文件、打包产物
EXCLUDE_SUFFIX = {".pt", ".db", ".db-wal", ".db-shm", ".pyc", ".zip", ".tar", ".gz"}
EXCLUDE_NAME = {".env", ".env.local"}


def collect_files():
    files = []
    for rel in INCLUDE_FILES:
        p = config.BASE_DIR / rel
        if p.exists():
            files.append(p)
    for rel in INCLUDE_DIRS:
        d = config.BASE_DIR / rel
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in EXCLUDE_SUFFIX:
                continue
            if p.name in EXCLUDE_NAME:
                continue
            files.append(p)
    return files


# ---------------------------------------------------------------- 快照
def make_snapshot():
    """导出题库与脱敏日志摘要，随包归档，便于离线复核与回滚比对。"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    rows = storage.qb_all()
    with open(EXPORT_DIR / "question_bank.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question", "answer", "intent", "entity"])
        for r in rows:
            w.writerow([r["question"], r["answer"], r["intent"], r["entity"]])

    stats = storage.graph_stats()
    (EXPORT_DIR / "graph_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    logs = storage.recent_logs(200)
    by_status = {}
    for x in logs:
        by_status[x["status"]] = by_status.get(x["status"], 0) + 1
    # 脱敏摘要：只统计状态与耗时，不落原始问句
    summary = [
        f"导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"题库条数: {len(rows)}",
        f"节点/关系: {stats['nodes']}/{stats['edges']}",
        f"最近 {len(logs)} 条问答状态分布: {by_status}",
        "说明: 本摘要不包含原始问句与答案，避免隐私外泄。",
    ]
    (EXPORT_DIR / "logs-summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return {"question_bank": len(rows), "nodes": stats["nodes"], "edges": stats["edges"]}


# ---------------------------------------------------------------- 打包与推送
def make_package(files):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"backup-{stamp}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        for f in files:
            tar.add(f, arcname=str(f.relative_to(config.BASE_DIR)))
    return out


def git_push(repo_url, workdir, token=""):
    """真实推送（默认不启用）。失败返回错误信息，不抛出；token 只用于本次 URL。"""
    try:
        repo_url = repo_url or config.GITHUB_REPO_URL
        token = token or config.GITHUB_TOKEN
        if not repo_url:
            return {"pushed": False, "error": "未配置 GITHUB_REPO_URL"}

        if not (workdir / ".git").exists():
            subprocess.run(["git", "init"], cwd=workdir, check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=workdir,
                           check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "-A"], cwd=workdir, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", f"backup: {datetime.now():%Y-%m-%d %H:%M}"],
                       cwd=workdir, capture_output=True, text=True)

        target = repo_url
        if token and repo_url.startswith("https://"):
            target = repo_url.replace("https://", f"https://{token}@", 1)
        subprocess.run(["git", "push", target, "HEAD"], cwd=workdir, check=True,
                       capture_output=True, text=True)
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=workdir,
                             check=True, capture_output=True, text=True).stdout.strip()
        return {"pushed": True, "commit": sha}
    except Exception as e:
        # 输出可能带 token，截断并去掉敏感片段
        msg = str(e)
        if config.GITHUB_TOKEN:
            msg = msg.replace(config.GITHUB_TOKEN, "***")
        return {"pushed": False, "error": msg[:300]}


def run_backup(dry_run=None, repo_url=None):
    """执行一次备份。dry_run 默认取 BACKUP_DRY_RUN。返回状态字典并落盘。"""
    dry_run = config.BACKUP_DRY_RUN if dry_run is None else dry_run
    snapshot = make_snapshot()
    files = collect_files()
    hits = scan_files(files)
    result = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": len(files),
        "snapshot": snapshot,
        "hits": len(hits),
        "hit_details": hits[:10],
        "dry_run": dry_run,
    }

    if hits:
        result.update({"status": "blocked", "package": None})
        _write_status(result)
        _write_report(result)
        return result

    package = make_package(files)
    result["package"] = package.name

    if dry_run:
        result["status"] = "dry_run"
    else:
        push = git_push(repo_url or config.GITHUB_REPO_URL, config.BASE_DIR)
        result["status"] = "pushed" if push.get("pushed") else "push_failed"
        result["git"] = push
    _write_status(result)
    _write_report(result)
    return result


def _write_status(result):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def _write_report(result):
    """证据文件：备份与扫描报告（方案 D5 证据要求）。"""
    lines = [
        f"备份时间: {result['time']}",
        f"状态: {result['status']}",
        f"文件数: {result['files']}",
        f"敏感命中: {result['hits']}",
        f"产物: {result.get('package') or '-'}",
        f"快照: {json.dumps(result.get('snapshot', {}), ensure_ascii=False)}",
        f"DRY_RUN: {result.get('dry_run')}",
    ]
    for h in result.get("hit_details", []):
        lines.append(f"命中: {h}")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def last_status():
    if not STATUS_FILE.exists():
        return {"status": "never"}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown"}
