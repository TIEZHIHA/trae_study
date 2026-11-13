# -*- coding: utf-8 -*-
"""敏感信息扫描：备份推送前的强制闸门。命中即中止。"""
import re

PATTERNS = [
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{16,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("password_assign", re.compile(r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]")),
]

TEXT_SUFFIX = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".env", ".sh", ".ps1",
               ".bat", ".html", ".css", ".js", ".toml", ".ini", ".cfg"}


def scan_text(text, name):
    hits = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            hits.append({"file": name, "kind": kind, "sample": m.group(0)[:24]})
    return hits


def scan_files(files):
    """只扫文本类文件，二进制跳过。返回命中列表。"""
    hits = []
    for f in files:
        if f.suffix.lower() not in TEXT_SUFFIX:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        hits.extend(scan_text(text, f.name))
    return hits
