# -*- coding: utf-8 -*-
"""
图谱体检与修复（方案 A10）：
  可检出并修复四类问题：
    1. 重复节点    同一名称挂在多个 Label 下
    2. 孤立节点    没有任何关系的节点
    3. 反向边      目标端是 Disease，违反“Disease -> 目标”方向
    4. 乱码节点    名称含替换符或 URL 转义残留

所有动作写入 logs/graph-doctor.log，修复后重跑建图数量不翻倍（MERGE 幂等）。
"""
import json
import re
from datetime import datetime

import config

BAD_NAME = re.compile(r"[\ufffd]|%[0-9A-Fa-f]{2}")


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def audit(conn):
    """返回四类问题清单，不做任何修改。"""
    nodes = _rows(conn, "SELECT label, name FROM nodes")
    by_name = {}
    for n in nodes:
        by_name.setdefault(n["name"], []).append(n["label"])

    duplicates = [{"name": k, "labels": v} for k, v in by_name.items() if len(v) > 1]
    orphans = _rows(conn, """
        SELECT label, name FROM nodes n
        WHERE NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE (e.src_label=n.label AND e.src_name=n.name)
               OR (e.dst_label=n.label AND e.dst_name=n.name))
    """)
    reverse = _rows(conn, "SELECT src_label, src_name, rel, dst_label, dst_name FROM edges "
                          "WHERE dst_label='Disease'")
    mojibake = [n for n in nodes if BAD_NAME.search(n["name"])]
    return {"duplicate": duplicates, "orphan": orphans,
            "reverse": reverse, "mojibake": mojibake}


def _delete_node(conn, label, name):
    conn.execute("DELETE FROM edges WHERE (src_label=? AND src_name=?) "
                 "OR (dst_label=? AND dst_name=?)", (label, name, label, name))
    conn.execute("DELETE FROM nodes WHERE label=? AND name=?", (label, name))


def _repair_pass(conn, issues):
    """执行一轮修复，返回动作；删除边可能让新节点变孤立，由外层循环兜底。"""
    actions = []
    for n in issues["mojibake"]:
        actions.append(f"删除乱码节点 {n['label']}:{n['name']}")
        _delete_node(conn, n["label"], n["name"])

    if issues["reverse"]:
        actions.append(f"删除反向边 {len(issues['reverse'])} 条")
        conn.execute("DELETE FROM edges WHERE dst_label='Disease'")

    for dup in issues["duplicate"]:
        keep = "Disease" if "Disease" in dup["labels"] else dup["labels"][0]
        for label in dup["labels"]:
            if label == keep:
                continue
            actions.append(f"合并重复节点 {label}:{dup['name']} -> {keep}")
            _delete_node(conn, label, dup["name"])

    for n in issues["orphan"]:
        actions.append(f"删除孤立节点 {n['label']}:{n['name']}")
        _delete_node(conn, n["label"], n["name"])
    return actions


def repair(conn, dry_run=False):
    """按 乱码 -> 反向边 -> 重复 -> 孤立 逐轮修复，直到体检干净（最多 5 轮）。"""
    first = audit(conn)
    before = _counts(first)
    actions = []
    if dry_run:
        return {"dry_run": True, "before": before,
                "actions": [f"{k}:{v}" for k, v in before.items() if v]}

    for _ in range(5):
        issues = audit(conn)
        if not any(issues.values()):
            break
        actions.extend(_repair_pass(conn, issues))
        conn.commit()
    return {"dry_run": False, "actions": actions, "before": before}


def _counts(issues):
    return {k: len(v) for k, v in issues.items()}


def write_log(result, tag="repair"):
    line = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tag": tag,
        "before": result.get("before", {}),
        "actions": result.get("actions", []),
    }
    with open(config.LOGS_DIR / "graph-doctor.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def inject_demo(conn):
    """向指定连接注入四类脏数据，仅用于验收演练（空库也能独立复现）。"""
    conn.execute("INSERT OR IGNORE INTO nodes(label,name,alias,desc,source,created_at) "
                 "VALUES('Disease','重复病X','','','demo',datetime('now'))")
    conn.execute("INSERT OR IGNORE INTO nodes(label,name,alias,desc,source,created_at) "
                 "VALUES('Symptom','重复病X','','','demo',datetime('now'))")
    conn.execute("INSERT OR IGNORE INTO nodes(label,name,alias,desc,source,created_at) "
                 "VALUES('Drug','孤立药X','','','demo',datetime('now'))")
    conn.execute("INSERT OR IGNORE INTO edges(src_label,src_name,rel,dst_label,dst_name,source,created_at) "
                 "VALUES('Symptom','重复病X','HAS_SYMPTOM','Disease','重复病X','demo',datetime('now'))")
    conn.execute("INSERT OR IGNORE INTO nodes(label,name,alias,desc,source,created_at) "
                 "VALUES('Disease','风热感冒\ufffd','','','demo',datetime('now'))")
    conn.commit()
    return audit(conn)


if __name__ == "__main__":
    import storage
    storage.init_db()
    conn = storage.get_conn()
    print("体检：", json.dumps(audit(conn), ensure_ascii=False, indent=1))
    result = repair(conn)
    write_log(result)
    print("修复：", json.dumps(result, ensure_ascii=False, indent=1))
