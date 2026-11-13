# -*- coding: utf-8 -*-
"""
清洗与解析：clean(raw) -> record
医学语义硬约束：否定词、时间、禁忌、剂量不误删，只做空白/符号/去重处理。
"""
import json
import re

from schema import FIELD_RELATION

# 章节标题 -> 字段名
SECTION_MAP = {
    "药物": "drug",
    "用药": "drug",
    "药品": "drug",
    "症状": "symptom",
    "症状表现": "symptom",
    "检查": "check",
    "相关检查": "check",
    "预防": "prevent",
    "预防措施": "prevent",
}

# 分隔符：中英文逗号、顿号、分号、竖线、换行
SPLIT_RE = re.compile(r"[、，,；;\n\|]+")


def clean_text(s):
    """None 保护 -> 去 HTML 标签 -> HTML 实体 -> 空白归一 -> strip。"""
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"<[^>]+>", "", s)          # 去标签
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = s.replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"[ \t\u3000]+", " ", s)     # 空白归一（保留换行用于分节）
    return s.strip()


def normalize_list(value):
    """切分 -> 逐项清洗 -> 去空 -> 保序去重。支持 list 与分隔符字符串两种输入。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = []
        for v in value:
            raw_items.extend(SPLIT_RE.split(str(v)))
    else:
        raw_items = SPLIT_RE.split(str(value))

    seen, out = set(), []
    for item in raw_items:
        item = clean_text(item).strip(" .。·-—")
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def parse_markdown(text, source):
    """
    解析 Markdown 语料：
        # 疾病名
        别名: xx, yy
        简介: ...
        ## 药物 / 症状 / 检查 / 预防
        - 条目
    """
    record = {
        "name": "", "alias": [], "desc": "", "source": source,
        "drug": [], "symptom": [], "check": [], "prevent": [],
    }
    current_field = None
    for raw_line in text.splitlines():
        line = clean_text(raw_line)
        if not line:
            continue
        if line.startswith("# "):
            record["name"] = line[2:].strip()
            current_field = None
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            current_field = SECTION_MAP.get(title)
            continue
        # 头部元信息
        if current_field is None:
            key, sep, val = line.partition(":")
            if not sep:
                key, sep, val = line.partition("：")
            if sep:
                key, val = key.strip(), val.strip()
                if key in ("别名", "alias"):
                    record["alias"] = normalize_list(val)
                elif key in ("简介", "描述", "desc"):
                    record["desc"] = val
            continue
        # 列表项
        item = re.sub(r"^[-*+]\s*", "", line)
        record[current_field].append(item)

    # 列表字段统一走 normalize_list，保证无空值/重复
    for key in ("drug", "symptom", "check", "prevent"):
        record[key] = normalize_list(record[key])
    return record


def parse_json(text, source):
    data = json.loads(text)
    record = {
        "name": clean_text(data.get("name")),
        "alias": normalize_list(data.get("alias")),
        "desc": clean_text(data.get("desc")),
        "source": source,
    }
    for key in ("drug", "symptom", "check", "prevent"):
        record[key] = normalize_list(data.get(key))
    return record


def parse_document(text, source):
    """入口：按扩展名/内容自动选择解析器，产出的 record 字段顺序固定。"""
    text = clean_text(text) if not text.strip().startswith("{") else text.strip()
    if text.lstrip().startswith("{"):
        return parse_json(text, source)
    return parse_markdown(text, source)


def validate_record(record):
    """返回 (ok, reason)。疾病名为空直接拒收，避免污染图谱。"""
    if not record.get("name"):
        return False, "缺少疾病名称（# 标题）"
    if not any(record.get(k) for k in FIELD_RELATION):
        return False, "没有任何可用关系字段（药物/症状/检查/预防）"
    return True, ""
