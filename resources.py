# -*- coding: utf-8 -*-
"""
资产导出（方案 A2）：把图谱沉淀成可交付、可复现的四类资产。
  1. resource/dict/entity_dict.json    实体词典（词 -> Label + 规范名）
  2. resource/entity_table.csv         实体表（含别名、简介、来源）
  3. resource/relation_candidates.csv  关系候选表（三元组候选）
  4. data/train/ner_bio.txt            训练集（BIO 标注，由 models.dataset 生成）

每次自动入库后刷新，保证“图谱是唯一事实源，资产是它的投影”。
"""
import csv
import json

import config
import storage
from schema import FIELD_RELATION


def export_entity_dict():
    """实体词典：词（含别名）-> {label, canonical}，供分词与模型对齐。"""
    data = {}
    for name, label, canonical in storage.all_names():
        if name and name not in data:
            data[name] = {"label": label, "canonical": canonical}
    path = config.DICT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(data)


def export_entity_table():
    """实体表：一行一个节点，保留别名与来源，便于人工核对。"""
    conn = storage.get_conn()
    rows = conn.execute(
        "SELECT label, name, alias, desc, source FROM nodes ORDER BY label, name"
    ).fetchall()
    path = config.ASSET_DIR / "entity_table.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "name", "alias", "desc", "source"])
        for r in rows:
            w.writerow([r["label"], r["name"], r["alias"], r["desc"], r["source"]])
    return len(rows)


def export_relation_candidates():
    """关系候选表：一行一条边，方向固定 Disease -> 目标实体。"""
    conn = storage.get_conn()
    rows = conn.execute(
        """SELECT src_label, src_name, rel, dst_label, dst_name, source
           FROM edges ORDER BY src_label, src_name, rel, dst_name"""
    ).fetchall()
    path = config.ASSET_DIR / "relation_candidates.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src_label", "src_name", "rel", "dst_label", "dst_name", "source"])
        for r in rows:
            w.writerow([r[c] for c in ("src_label", "src_name", "rel",
                                       "dst_label", "dst_name", "source")])
    return len(rows)


def export_all(with_training=True):
    """导出全部资产。训练集生成失败不阻塞主流程，只记录错误。"""
    stats = {
        "dict": export_entity_dict(),
        "entities": export_entity_table(),
        "relations": export_relation_candidates(),
        "train": 0,
        "error": "",
    }
    if with_training:
        try:
            from models.dataset import build_training_files
            stats["train"] = build_training_files()
        except Exception as e:      # 训练集生成属于增强项，失败不影响入库
            stats["error"] = f"{type(e).__name__}: {e}"
    return stats
