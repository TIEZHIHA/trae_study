# -*- coding: utf-8 -*-
"""
建图：record -> triples -> MERGE 入图。
统一从 Disease 出发连向目标实体，复用节点，跳过空值，统计并写日志。
"""
from clean import validate_record
from schema import DISEASE, FIELD_RELATION
import storage


def extract_triples(record):
    """
    extract(record) -> triples
    triple = (src_label, src_name, rel, dst_label, dst_name, source)
    """
    ok, reason = validate_record(record)
    if not ok:
        return []
    triples = []
    src = record["name"]
    source = record.get("source", "")
    for field, (dst_label, rel) in FIELD_RELATION.items():
        for item in record.get(field) or []:
            if not item:
                continue
            triples.append((DISEASE, src, rel, dst_label, item, source))
    return triples


def merge_record(record):
    """把一条清洗后的记录写进图谱，返回新增统计。"""
    stats = {"nodes_added": 0, "edges_added": 0, "skipped_empty": 0}
    if not record.get("name"):
        stats["skipped_empty"] += 1
        return stats

    # 疾病节点（带 desc / alias / source）
    alias = ",".join(record.get("alias") or [])
    if storage.merge_node(
        DISEASE, record["name"], alias=alias, desc=record.get("desc", ""),
        source=record.get("source", ""),
    ):
        stats["nodes_added"] += 1

    # 关系与目标节点
    for src_label, src_name, rel, dst_label, dst_name, source in extract_triples(record):
        if not dst_name:
            stats["skipped_empty"] += 1
            continue
        if storage.merge_node(dst_label, dst_name, source=source):
            stats["nodes_added"] += 1
        if storage.merge_edge(src_label, src_name, rel, dst_label, dst_name, source):
            stats["edges_added"] += 1

    return stats


def rebuild_from_clean(truncate=False):
    """从 clean_kb 全量重建图谱（等价于重跑建图，用于验证幂等/修复）。

    truncate=True 时先清空节点与关系，用于语料内容变更后的替换，
    避免旧版本中已删除的关系残留在图里。
    """
    import json
    conn = storage.get_conn()
    if truncate:
        conn.execute("DELETE FROM nodes")
        conn.execute("DELETE FROM edges")
        conn.commit()
    rows = conn.execute("SELECT doc_id, record FROM clean_kb").fetchall()
    total = {"nodes_added": 0, "edges_added": 0, "skipped_empty": 0}
    for r in rows:
        record = json.loads(r["record"])
        s = merge_record(record)
        for k in total:
            total[k] += s[k]
    from schema import SYMPTOM_ALIASES
    storage.ensure_symptom_aliases(SYMPTOM_ALIASES)
    return total
