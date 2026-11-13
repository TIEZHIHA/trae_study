# -*- coding: utf-8 -*-
"""题库自动生成：从图谱自动产出问句 + 标准答案，作为回归验证集。"""
from schema import (
    INTENT_ASK_CHECK, INTENT_ASK_DRUG, INTENT_ASK_PREVENT, INTENT_ASK_SYMPTOM,
    TEMPLATES,
)
import storage

# 字段 -> (问句模板, 意图)
QUESTION_RULES = [
    ("drug", "{name}吃什么药", INTENT_ASK_DRUG),
    ("symptom", "{name}有哪些症状", INTENT_ASK_SYMPTOM),
    ("check", "{name}需要做什么检查", INTENT_ASK_CHECK),
    ("prevent", "怎么预防{name}", INTENT_ASK_PREVENT),
]


def build_answer(intent, entity, items):
    """按模板拼答案，不生成医学结论。"""
    return TEMPLATES[intent].format(entity=entity, items="、".join(items))


def generate_for_record(record):
    """为一条记录生成题库条目，返回新增条数。"""
    name = record.get("name")
    if not name:
        return 0
    added = 0
    for field, q_tpl, intent in QUESTION_RULES:
        items = record.get(field) or []
        if not items:
            continue
        question = q_tpl.format(name=name)
        answer = build_answer(intent, name, items)
        if storage.qb_add(question, answer, intent, name):
            added += 1
    return added


def generate_all():
    """从 clean_kb 全量重生成题库（幂等：已存在问句跳过）。"""
    import json
    conn = storage.get_conn()
    rows = conn.execute("SELECT record FROM clean_kb").fetchall()
    total = 0
    for r in rows:
        total += generate_for_record(json.loads(r["record"]))
    return total
