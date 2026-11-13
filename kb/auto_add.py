# -*- coding: utf-8 -*-
"""
知识库 / 题库自动添加。
流水线：
  扫描 -> 内容哈希去重 -> 解析 -> 清洗 -> 实体与关系抽取
  -> 写 raw_kb -> 写 clean_kb ->（审核开关）-> MERGE 入图
  -> 生成问句 -> 导出资产 -> 写同步日志

幂等：doc_id = sha256(相对路径 + 内容)，已存在直接跳过。
并发：GUI 里目录监听、定时同步、HTTP 手动同步可能同时触发，用模块级锁串行化。
"""
import hashlib
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import config
from build_graph import merge_record
from clean import parse_document, validate_record
from kb import question_bank
from segment import build_dict
import storage

SUPPORTED = {".md", ".txt", ".json", ".html"}
_SYNC_LOCK = threading.Lock()


def iter_files(inbox=None):
    """遍历 inbox，按扩展名过滤，稳定排序保证可复现。"""
    inbox = Path(inbox or config.INBOX_DIR)
    if not inbox.exists():
        return []
    files = [p for p in inbox.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED]
    return sorted(files)


def make_doc_id(path):
    """相对路径 + 内容做 sha256，同文件重复投放不会重复入图；内容变更则视为新文档。"""
    p = Path(path)
    try:
        rel = p.relative_to(config.INBOX_DIR)
    except ValueError:
        rel = p.name
    h = hashlib.sha256()
    h.update(str(rel).encode("utf-8"))
    h.update(p.read_bytes())
    return h.hexdigest()


def _read_text(path):
    """编码探测：优先 utf-8，失败退回 gbk/latin-1，避免中文语料读崩。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def process_file(path, require_review=None):
    """处理单个文件，返回 (状态, 详情)。状态：added / pending / skipped / invalid。"""
    require_review = config.KB_REQUIRE_REVIEW if require_review is None else require_review
    doc_id = make_doc_id(path)
    if storage.doc_exists(doc_id):
        return "skipped", {"doc_id": doc_id, "reason": "已入库"}

    text = _read_text(path)
    storage.save_raw(doc_id, str(path), text)  # 原始永久保留

    record = parse_document(text, source=str(path))
    ok, reason = validate_record(record)
    if not ok:
        return "invalid", {"doc_id": doc_id, "reason": reason}

    # 审核模式：先入 pending 队列，人工确认后再入图
    if require_review:
        storage.save_pending(doc_id, str(path), record)
        return "pending", {"doc_id": doc_id, "name": record["name"], "reason": "等待人工审核"}

    storage.save_clean(doc_id, record)
    stats = merge_record(record)
    questions = question_bank.generate_for_record(record)
    storage.mark_doc(doc_id, str(path))

    return "added", {
        "doc_id": doc_id,
        "name": record["name"],
        "nodes_added": stats["nodes_added"],
        "edges_added": stats["edges_added"],
        "questions": questions,
    }


def approve(doc_id):
    """审核通过：从 pending 取出并完成入图与建题。"""
    record = storage.pop_pending(doc_id)
    if not record:
        return {"ok": False, "reason": "pending 中不存在该文档"}
    storage.save_clean(doc_id, record)
    stats = merge_record(record)
    questions = question_bank.generate_for_record(record)
    storage.mark_doc(doc_id, record.get("source", ""))
    build_dict(force=True)
    return {"ok": True, "name": record.get("name"), "questions": questions, **stats}


def sync_once(inbox=None):
    """一次完整同步，返回统计。可重复执行，数量不翻倍。"""
    with _SYNC_LOCK:
        started = time.perf_counter()
        stats = {"scanned": 0, "added": 0, "pending": 0, "skipped": 0,
                 "invalid": 0, "questions": 0, "details": []}
        for path in iter_files(inbox):
            stats["scanned"] += 1
            status, info = process_file(path)
            if status == "added":
                stats["added"] += 1
                stats["questions"] += info.get("questions", 0)
            elif status == "pending":
                stats["pending"] += 1
            elif status == "skipped":
                stats["skipped"] += 1
            else:
                stats["invalid"] += 1
            stats["details"].append({"file": Path(path).name, "status": status, **info})

        # 图谱变动后词典需要重建，否则新实体识别不到
        build_dict(force=True)

        # 资产投影（词典/实体表/关系候选表/训练集），失败不阻塞入库
        try:
            from resources import export_all
            stats["assets"] = export_all(with_training=stats["added"] > 0)
        except Exception as e:
            stats["assets"] = {"error": f"{type(e).__name__}: {e}"}

        stats["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        _write_log(stats)
        _write_build_log(stats)
        return stats


def _write_build_log(stats):
    """建图统计日志（方案 A3）：每次同步记录增量与全量节点/关系数。"""
    g = storage.graph_stats()
    line = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "added_docs": stats["added"],
        "questions": stats["questions"],
        "nodes_total": g["nodes"],
        "edges_total": g["edges"],
        "by_label": g["by_label"],
        "by_rel": g["by_rel"],
    }
    with open(config.LOGS_DIR / "build-graph.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _write_log(stats):
    line = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanned": stats["scanned"],
        "added": stats["added"],
        "pending": stats.get("pending", 0),
        "skipped": stats["skipped"],
        "invalid": stats["invalid"],
        "questions": stats["questions"],
        "elapsed_ms": stats.get("elapsed_ms", 0),
    }
    with open(config.LOGS_DIR / "kb-sync.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def inbox_stats():
    """给前端面板用的知识库统计（四项核心数值 + 审核队列）。"""
    total = len(iter_files())
    processed = storage.get_conn().execute(
        "SELECT COUNT(*) c FROM doc_registry").fetchone()["c"]
    return {
        "inbox_files": total,
        "docs_processed": processed,
        "questions": storage.qb_count(),
        "graph": storage.graph_stats(),
        "pending": storage.pending_count(),
    }
