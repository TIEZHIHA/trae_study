# -*- coding: utf-8 -*-
"""
训练数据自动生成（BIO 标注 + 意图分类样本）。
事实源是图谱与题库：所有样本都由疾病名/别名 + 问句模板拼出来，
新增疾病后重新生成即可，不需要手工标注。

产物：
  data/train/ner_bio.txt        每行一句，token 形如 “风/B-Disease”
  data/train/intent_train.csv   text,intent
"""
import csv
import random

import config
import storage
from schema import (
    INTENT_ASK_CHECK, INTENT_ASK_DRUG, INTENT_ASK_PREVENT, INTENT_ASK_SYMPTOM,
)

# 实体识别模板（{e} 为疾病名或别名）
NER_TEMPLATES = [
    "{e}吃什么药", "怎么预防{e}", "{e}有哪些症状", "{e}需要做什么检查",
    "{e}严重吗", "我得了{e}怎么办", "{e}会不会传染", "请问{e}怎么调理",
    "怀疑是{e}", "{e}的注意事项", "{e}好治吗", "家里有人得了{e}",
]

PREFIXES = ["", "请问", "我想问一下", "帮我看看", "医生，", "最近"]
SUFFIXES = ["", "呢", "啊", "？", "谢谢"]

# 意图模板：第一版 4 类 + 第二版 5 类 + 无关问句
INTENT_TEMPLATES = {
    INTENT_ASK_DRUG: [
        "{e}吃什么药", "{e}用什么药", "{e}的常用药物有哪些", "治疗{e}的药品",
        "给{e}开点什么药",
    ],
    INTENT_ASK_SYMPTOM: [
        "{e}有哪些症状", "{e}有什么表现", "{e}的临床表现", "得了{e}会哪里不舒服",
    ],
    INTENT_ASK_CHECK: [
        "{e}需要做什么检查", "{e}要化验什么", "{e}怎么确诊", "{e}做什么检测",
    ],
    INTENT_ASK_PREVENT: [
        "怎么预防{e}", "如何预防{e}", "{e}要注意什么", "{e}怎么避免",
    ],
    "ask_interaction": [
        "{d1}和{d2}能一起吃吗", "{d1}和{d2}有相互作用吗", "这两种药同服会冲突吗",
        "{d1}能一起用吗",
    ],
    "ask_possible_disease": [
        "这些症状可能是什么病", "会不会是{e}", "我这种情况会得什么病",
    ],
    "ask_treatment_plan": [
        "{e}怎么治疗", "{e}的治疗方案", "如何治疗{e}", "{e}的治疗办法",
    ],
    "ask_cycle": [
        "{e}要治多久", "{e}的疗程多长", "{e}多久能好", "{e}治疗周期",
    ],
    "ask_symptom_desc": [
        "{e}的症状具体表现是什么样", "{e}症状的严重程度", "{e}的症状描述",
    ],
    "other": [
        "你好", "谢谢", "今天天气怎么样", "你是谁", "随便聊聊", "帮我订个闹钟",
    ],
}


def _iter_diseases():
    """返回 [(规范名, 别名列表)]，只取 Disease 节点。"""
    conn = storage.get_conn()
    rows = conn.execute(
        "SELECT name, alias FROM nodes WHERE label='Disease' ORDER BY name"
    ).fetchall()
    out = []
    for r in rows:
        alias = [a.strip() for a in (r["alias"] or "").split(",") if a.strip()]
        out.append((r["name"], alias))
    return out


def _iter_drugs():
    conn = storage.get_conn()
    rows = conn.execute("SELECT name FROM nodes WHERE label='Drug' ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def _bio_line(sentence, surface):
    """把句子转成 BIO 行：实体首字 B-Disease，其余 I-Disease。"""
    tokens = []
    start = sentence.find(surface)
    for i, ch in enumerate(sentence):
        if start >= 0 and start <= i < start + len(surface):
            tag = "B-Disease" if i == start else "I-Disease"
        else:
            tag = "O"
        tokens.append(f"{ch}/{tag}")
    return " ".join(tokens)


def build_ner_samples():
    """生成 NER 样本；同一疾病只保留主干名与别名各一次，避免重复。"""
    samples = set()
    for name, aliases in _iter_diseases():
        for surface in [name] + aliases:
            for tpl in NER_TEMPLATES:
                for pre in PREFIXES:
                    for suf in SUFFIXES:
                        sentence = f"{pre}{tpl.format(e=surface)}{suf}"
                        samples.add((sentence, surface))
    # 负样本：不含疾病实体的问句，让模型学会不硬标
    for q in ("那个东西能不能吃", "最近总是睡不好", "如何提高免疫力",
              "今天嗓子有点干", "这个药有什么副作用", "我该挂哪个科"):
        samples.add((q, ""))
    return sorted(samples)


def build_intent_samples():
    """生成意图样本：疾病 × 模板 + 题库既有问句。"""
    samples = set()
    diseases = _iter_diseases()
    drugs = _iter_drugs()
    for intent, templates in INTENT_TEMPLATES.items():
        for tpl in templates:
            if "{e}" in tpl:
                for name, aliases in diseases:
                    for surface in [name] + aliases:
                        samples.add((tpl.format(e=surface), intent))
            elif "{d1}" in tpl:
                for i, d1 in enumerate(drugs):
                    d2 = drugs[(i + 1) % len(drugs)]
                    samples.add((tpl.format(d1=d1, d2=d2), intent))
            else:
                samples.add((tpl, intent))
    # 题库问句直接作为监督信号
    for row in storage.qb_all():
        samples.add((row["question"], row["intent"]))
    return sorted(samples)


def build_training_files():
    """写出两个训练文件，返回样本总数。"""
    random.seed(2026)
    ner = build_ner_samples()
    intent = build_intent_samples()

    ner_path = config.TRAIN_DIR / "ner_bio.txt"
    with open(ner_path, "w", encoding="utf-8") as f:
        for sentence, surface in ner:
            f.write(_bio_line(sentence, surface) + "\n")

    intent_path = config.TRAIN_DIR / "intent_train.csv"
    with open(intent_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["text", "intent"])
        for text, intent in intent:
            w.writerow([text, intent])

    return len(ner) + len(intent)
