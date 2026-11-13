# -*- coding: utf-8 -*-
"""
采集与解析（方案 A1）：
  fetch_html(url)  带 UA、超时、重试、编码探测、大小上限、异常兜底
  parse_html(html) -> record  六字段（名称/别名/症状/药物/检查/预防）+ 简介
  crawl(urls)       抓取并写入 data/inbox/crawled/*.md，交给自动入库流水线

设计说明：
  - 页面结构千差万别，这里只做“标题 + 章节标题 + 列表项”的通用抽取，
    抽不出的字段留空，绝不猜测内容；
  - 网络失败不抛异常，返回 (None, 原因)，由调用方决定是否记录；
  - 离线样例放在 data/crawl_samples/，验收时无需联网即可跑通 A-V1。
"""
import re
import time
from pathlib import Path

from clean import normalize_list, validate_record

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 MedQA-Crawler/1.0")

MAX_BYTES = 2 * 1024 * 1024      # 单页上限 2 MB
TIMEOUT = 8                      # 秒
RETRIES = 2

# 章节标题 -> record 字段（比 clean.SECTION_MAP 更宽，覆盖网页常见写法）
HTML_SECTION_MAP = {
    "常用药物": "drug", "推荐药物": "drug", "治疗药物": "drug", "药品": "drug",
    "用药": "drug", "药物": "drug",
    "临床表现": "symptom", "主要症状": "symptom", "症状表现": "symptom", "症状": "symptom",
    "辅助检查": "check", "相关检查": "check", "诊断检查": "check", "检查": "check",
    "预防措施": "prevent", "日常护理": "prevent", "注意事项": "prevent", "预防": "prevent",
}

_TAG_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC = re.compile(
    r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']", re.S | re.I
)
_HEADING = re.compile(r"<(h2|h3)[^>]*>(.*?)</\1>", re.S | re.I)
_LIST_ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
_PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def strip_tags(s):
    return re.sub(r"\s+", " ", _TAG.sub("", s or "")).strip()


def fetch_html(url, timeout=TIMEOUT, retries=RETRIES):
    """
    返回 (html, 错误原因)。requests 缺失或网络异常时降级为错误返回，不抛出。
    """
    try:
        import requests
    except ImportError:
        return None, "requests 未安装，无法联网采集（可使用本地样例）"

    last = ""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            resp.raise_for_status()
            raw = resp.content[:MAX_BYTES]
            # 编码优先级：响应头 -> apparent_encoding -> utf-8
            enc = resp.encoding or resp.apparent_encoding or "utf-8"
            try:
                html = raw.decode(enc, errors="replace")
            except LookupError:
                html = raw.decode("utf-8", errors="replace")
            return html, ""
        except Exception as e:                 # 超时/连接/HTTP 错误统一兜底
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))   # 退避重试
    return None, last


def parse_html(html, source=""):
    """从 HTML 抽取疾病记录；抽不到名称返回空记录，由 validate_record 拒收。"""
    text = _COMMENT.sub("", _TAG_SCRIPT.sub("", html or ""))

    head = _H1.search(text) or _TITLE.search(text)
    name = strip_tags(head.group(1)) if head else ""
    # 标题常见写法：“风热感冒（风热型感冒）- 某百科”，只取主干
    name = re.split(r"[（(｜|_\-]", name)[0].strip()

    desc = ""
    m = _META_DESC.search(text)
    if m:
        desc = strip_tags(m.group(1))

    record = {
        "name": name, "alias": [], "desc": desc, "source": source,
        "drug": [], "symptom": [], "check": [], "prevent": [],
    }

    # 按 h2/h3 切块，块内取 li，退化时取 p
    marks = list(_HEADING.finditer(text))
    for i, mark in enumerate(marks):
        title = strip_tags(mark.group(2))
        field = HTML_SECTION_MAP.get(title)
        start = mark.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[start:end]
        items = [strip_tags(x) for x in _LIST_ITEM.findall(block)]
        if not items:
            items = [strip_tags(x) for x in _PARAGRAPH.findall(block)]
        if field:
            record[field].extend([x for x in items if x])
        elif not desc and items:
            desc = items[0]

    # 头部“别名：A、B”行
    alias_match = re.search(r"别名[:：]\s*([^<\n]+)", text)
    if alias_match:
        record["alias"] = normalize_list(alias_match.group(1))

    for key in ("drug", "symptom", "check", "prevent"):
        record[key] = normalize_list(record[key])
    return record


def crawl_file(path):
    """离线解析本地 HTML 样例（验收 A-V1 用）。"""
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_html(html, source=str(path))


def record_to_markdown(record):
    """把记录还原成 inbox 可解析的 Markdown，保证“采集 → 入库”闭环。"""
    lines = [f"# {record['name']}", ""]
    if record.get("alias"):
        lines.append("别名：" + "、".join(record["alias"]))
    if record.get("desc"):
        lines.append("简介：" + record["desc"])
    lines.append("")
    for field, title in (("drug", "药物"), ("symptom", "症状"),
                         ("check", "检查"), ("prevent", "预防")):
        items = record.get(field) or []
        if not items:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {x}" for x in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def crawl(urls, out_dir=None, sleep=0.5):
    """
    批量采集：抓取 -> 解析 -> 校验 -> 写 Markdown。
    返回 {"ok": n, "failed": [...], "files": [...]}，失败不中断批次。
    """
    from config import INBOX_DIR

    out_dir = Path(out_dir or (INBOX_DIR / "crawled"))
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"ok": 0, "failed": [], "files": []}
    for url in urls:
        html, err = fetch_html(url)
        if html is None:
            result["failed"].append({"url": url, "reason": err})
            continue
        record = parse_html(html, source=url)
        ok, reason = validate_record(record)
        if not ok:
            result["failed"].append({"url": url, "reason": reason})
            continue
        # 文件名用疾病名，避免 URL 转义问题
        target = out_dir / f"{record['name']}.md"
        target.write_text(record_to_markdown(record), encoding="utf-8")
        result["ok"] += 1
        result["files"].append(str(target))
        time.sleep(sleep)
    return result
