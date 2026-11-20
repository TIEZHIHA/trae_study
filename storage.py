# -*- coding: utf-8 -*-
"""
存储层：用 SQLite 单文件承载方案里的 MongoDB（原始/清洗/题库/日志）与 Neo4j（节点/关系）。
表结构与字段名严格对齐方案：
  raw_kb        原始集合（永久保留不覆盖）
  clean_kb      清洗集合（可迭代）
  nodes / edges 图谱（Label + name 唯一，方向 Disease -> 目标实体）
  question_bank 自动生成题库（回归验证集）
  qa_logs       问答日志（错误答案回流入口）
"""
import json
import sqlite3
from datetime import datetime

from config import DB_PATH

# 单连接复用：FastAPI 是多线程的，check_same_thread=False 允许跨线程使用；
# 每次写操作自行 commit，读操作无副作用。
_CONN = None


def get_conn():
    global _CONN
    if _CONN is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL")  # 读写并发更稳
    return _CONN


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    """建表 + 建唯一约束。重复执行安全（IF NOT EXISTS）。"""
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS raw_kb (
            doc_id     TEXT PRIMARY KEY,
            path       TEXT,
            content    TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS clean_kb (
            doc_id     TEXT PRIMARY KEY,
            record     TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS nodes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            label      TEXT NOT NULL,
            name       TEXT NOT NULL,
            alias      TEXT DEFAULT '',
            desc       TEXT DEFAULT '',
            source     TEXT DEFAULT '',
            created_at TEXT,
            UNIQUE(label, name)
        );

        CREATE TABLE IF NOT EXISTS edges (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            src_label  TEXT NOT NULL,
            src_name   TEXT NOT NULL,
            rel        TEXT NOT NULL,
            dst_label  TEXT NOT NULL,
            dst_name   TEXT NOT NULL,
            source     TEXT DEFAULT '',
            created_at TEXT,
            UNIQUE(src_label, src_name, rel, dst_label, dst_name)
        );

        CREATE TABLE IF NOT EXISTS question_bank (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            question   TEXT UNIQUE,
            answer     TEXT,
            intent     TEXT,
            entity     TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS qa_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            question   TEXT,
            entity     TEXT,
            intent     TEXT,
            status     TEXT,
            answer     TEXT,
            ner_conf   REAL,
            intent_conf REAL,
            elapsed_ms REAL,
            created_at TEXT
        );

        -- 已处理文档登记表，等价于方案里的 kb.mark(doc_id)
        CREATE TABLE IF NOT EXISTS doc_registry (
            doc_id     TEXT PRIMARY KEY,
            path       TEXT,
            added_at   TEXT
        );

        -- 审核队列：KB_REQUIRE_REVIEW=true 时先落这里，人工确认后再入图
        CREATE TABLE IF NOT EXISTS pending_kb (
            doc_id     TEXT PRIMARY KEY,
            path       TEXT,
            record     TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_label, src_name, rel);
        CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
        """
    )
    conn.commit()


# ---------------------------------------------------------------- 原始层 / 清洗层
def save_raw(doc_id, path, content):
    """原始数据只插不改：已存在则跳过，保证可回溯、可重跑。"""
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO raw_kb(doc_id, path, content, created_at) VALUES(?,?,?,?)",
        (doc_id, path, content, now()),
    )
    conn.commit()


def save_clean(doc_id, record: dict):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO clean_kb(doc_id, record, created_at) VALUES(?,?,?)",
        (doc_id, json.dumps(record, ensure_ascii=False), now()),
    )
    conn.commit()


def doc_exists(doc_id):
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM doc_registry WHERE doc_id=?", (doc_id,)).fetchone()
    return row is not None


def mark_doc(doc_id, path):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO doc_registry(doc_id, path, added_at) VALUES(?,?,?)",
        (doc_id, path, now()),
    )
    conn.commit()


def doc_by_path(path):
    """按文件路径查已登记的 doc_id，用于语料内容变更后的替换。"""
    conn = get_conn()
    row = conn.execute("SELECT doc_id FROM doc_registry WHERE path=?", (path,)).fetchone()
    return row["doc_id"] if row else None


def remove_doc(doc_id):
    """删除某版本文档的登记、原始与清洗记录（图中的残留由全量重建清掉）。"""
    conn = get_conn()
    for sql in ("DELETE FROM clean_kb WHERE doc_id=?",
                "DELETE FROM raw_kb WHERE doc_id=?",
                "DELETE FROM doc_registry WHERE doc_id=?"):
        conn.execute(sql, (doc_id,))
    conn.commit()


def qb_delete_entity(entity):
    """语料更新时清掉该实体的旧问句，避免题库保留过期答案。"""
    conn = get_conn()
    conn.execute("DELETE FROM question_bank WHERE entity=?", (entity,))
    conn.commit()


# ---------------------------------------------------------------- 图谱
def merge_node(label, name, alias="", desc="", source="clean_kb"):
    """MERGE 语义：按 (label, name) 去重；已存在则补全空字段，不重复插入。"""
    name = (name or "").strip()
    if not name:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT id, alias, desc FROM nodes WHERE label=? AND name=?", (label, name)
    ).fetchone()
    if row:
        new_alias = row["alias"] or alias
        new_desc = row["desc"] or desc
        conn.execute(
            "UPDATE nodes SET alias=?, desc=? WHERE id=?",
            (new_alias, new_desc, row["id"]),
        )
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO nodes(label, name, alias, desc, source, created_at) VALUES(?,?,?,?,?,?)",
        (label, name, alias, desc, source, now()),
    )
    conn.commit()
    return True


def merge_edge(src_label, src_name, rel, dst_label, dst_name, source="clean_kb"):
    """MERGE 关系：四元组唯一，重跑建图不会翻倍。"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT OR IGNORE INTO edges(src_label, src_name, rel, dst_label, dst_name, source, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (src_label, src_name, rel, dst_label, dst_name, source, now()),
    )
    conn.commit()
    return cur.rowcount > 0


def query_facts(entity, rel):
    """按 疾病名 + 关系 查目标实体，返回带来源的证据列表。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT dst_label, dst_name, source FROM edges
           WHERE src_label=? AND src_name=? AND rel=?
           ORDER BY id""",
        ("Disease", entity, rel),
    ).fetchall()
    return [dict(r) for r in rows]


def diseases_by_symptom(symptom):
    """反向查询：症状 -> 可能疾病。底层仍是 Disease -HAS_SYMPTOM-> Symptom 的正向边。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT src_name, source FROM edges
           WHERE rel='HAS_SYMPTOM' AND dst_label='Symptom' AND dst_name=?
           ORDER BY src_name""",
        (symptom,),
    ).fetchall()
    return [{"disease": r["src_name"], "source": r["source"]} for r in rows]


def symptoms_with_diseases(limit=8):
    """图谱中关联疾病最多的症状，供题库自动生成症状驱动问句。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT dst_name, COUNT(*) AS c FROM edges
           WHERE rel='HAS_SYMPTOM' AND dst_label='Symptom'
           GROUP BY dst_name ORDER BY c DESC, dst_name LIMIT ?""",
        (limit,),
    ).fetchall()
    return [r["dst_name"] for r in rows]


def ensure_symptom_aliases(mapping):
    """把口语同义词追加到症状节点的 alias 字段，幂等；规范名不存在则跳过。"""
    conn = get_conn()
    added = 0
    for alias, canonical in mapping.items():
        row = conn.execute(
            "SELECT alias FROM nodes WHERE label='Symptom' AND name=?", (canonical,)
        ).fetchone()
        if not row:
            continue
        parts = [p.strip() for p in (row["alias"] or "").replace("，", ",").split(",")
                 if p.strip()]
        if alias in parts:
            continue
        parts.append(alias)
        conn.execute(
            "UPDATE nodes SET alias=? WHERE label='Symptom' AND name=?",
            (",".join(parts), canonical),
        )
        added += 1
    conn.commit()
    return added


def all_names():
    """返回 [(name, label, canonical)]，供实体词典使用（别名指向规范名）。"""
    conn = get_conn()
    rows = conn.execute("SELECT label, name, alias FROM nodes").fetchall()
    out = []
    for r in rows:
        out.append((r["name"], r["label"], r["name"]))
        if r["alias"]:
            for a in r["alias"].replace("，", ",").split(","):
                a = a.strip()
                if a:
                    out.append((a, r["label"], r["name"]))
    return out


def find_disease(name):
    conn = get_conn()
    row = conn.execute(
        "SELECT name, desc, source FROM nodes WHERE label='Disease' AND name=?", (name,)
    ).fetchone()
    return dict(row) if row else None


def graph_stats():
    conn = get_conn()
    nodes = conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) c FROM edges").fetchone()["c"]
    by_label = {
        r["label"]: r["c"]
        for r in conn.execute("SELECT label, COUNT(*) c FROM nodes GROUP BY label").fetchall()
    }
    by_rel = {
        r["rel"]: r["c"]
        for r in conn.execute("SELECT rel, COUNT(*) c FROM edges GROUP BY rel").fetchall()
    }
    return {"nodes": nodes, "edges": edges, "by_label": by_label, "by_rel": by_rel}


# ---------------------------------------------------------------- 题库
def qb_add(question, answer, intent, entity):
    conn = get_conn()
    cur = conn.execute(
        """INSERT OR IGNORE INTO question_bank(question, answer, intent, entity, created_at)
           VALUES(?,?,?,?,?)""",
        (question, answer, intent, entity, now()),
    )
    conn.commit()
    return cur.rowcount > 0


def qb_all():
    conn = get_conn()
    rows = conn.execute(
        "SELECT question, answer, intent, entity FROM question_bank ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def qb_count():
    return get_conn().execute("SELECT COUNT(*) c FROM question_bank").fetchone()["c"]


# ---------------------------------------------------------------- 日志
def log_qa(question, entity, intent, status, answer, ner_conf, intent_conf, elapsed_ms):
    conn = get_conn()
    conn.execute(
        """INSERT INTO qa_logs(question, entity, intent, status, answer, ner_conf, intent_conf, elapsed_ms, created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (question, entity, intent, status, answer, ner_conf, intent_conf, elapsed_ms, now()),
    )
    conn.commit()


def recent_logs(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT question, entity, intent, status, elapsed_ms, created_at FROM qa_logs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def reset_db():
    """全量重建（仅验证脚本与开发使用）。"""
    conn = get_conn()
    conn.executescript(
        "DELETE FROM raw_kb; DELETE FROM clean_kb; DELETE FROM nodes;"
        "DELETE FROM edges; DELETE FROM question_bank; DELETE FROM qa_logs;"
        "DELETE FROM doc_registry; DELETE FROM pending_kb;"
    )
    conn.commit()


# ---------------------------------------------------------------- 审核队列
def save_pending(doc_id, path, record: dict):
    """审核模式下先入 pending_kb，不直接进图谱。"""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO pending_kb(doc_id, path, record, created_at) VALUES(?,?,?,?)",
        (doc_id, path, json.dumps(record, ensure_ascii=False), now()),
    )
    conn.commit()


def pending_all():
    conn = get_conn()
    rows = conn.execute(
        "SELECT doc_id, path, record, created_at FROM pending_kb ORDER BY created_at"
    ).fetchall()
    return [
        {
            "doc_id": r["doc_id"],
            "path": r["path"],
            "record": json.loads(r["record"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def pop_pending(doc_id):
    """取出并从队列删除，返回 record；不存在返回 None。"""
    conn = get_conn()
    row = conn.execute("SELECT record FROM pending_kb WHERE doc_id=?", (doc_id,)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM pending_kb WHERE doc_id=?", (doc_id,))
    conn.commit()
    return json.loads(row["record"])


def pending_count():
    return get_conn().execute("SELECT COUNT(*) c FROM pending_kb").fetchone()["c"]
