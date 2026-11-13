# -*- coding: utf-8 -*-
"""
分词与实体识别：双向最大匹配 + 启发式选择。
规则（方案步骤 5）：
  1. 窗口从最长词长递减尝试，未命中按单字切分；
  2. 优先词数更少的切分；
  3. 词数相同则单字词更少者优先；
  4. 医学专有词尽量保持完整。

词典由两部分组成：
  - 图谱实体词典（storage.all_names，含别名），label 为五类节点；
  - 基础医学词表（resource/dict/base_words.txt），label 记为 "_"，
    只参与切分，不参与实体识别，避免“感冒/药物”被当成图谱实体。
"""
import config
from storage import all_names

# 全局词典缓存：{词: (label, 规范名)}
_DICT = {}
_MAX_LEN = 1
_BASE_WORDS = set()


def load_base_words():
    """读取基础词表；文件缺失时用内置词兜底，保证离线可用。"""
    global _BASE_WORDS
    if _BASE_WORDS:
        return _BASE_WORDS
    words = set()
    path = config.BASE_WORDS_PATH
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w and not w.startswith("#"):
                words.add(w)
    if not words:
        words = set("感冒 药物 药品 治疗 用药 症状 检查 预防 疾病 发烧 咳嗽 头痛".split())
    _BASE_WORDS = words
    return words


def build_dict(force=False):
    """合并实体词典与基础词表，返回切分用词典。图谱变化后调用 force=True。"""
    global _DICT, _MAX_LEN
    if _DICT and not force:
        return _DICT
    d = {}
    for name, label, canonical in all_names():
        if not name:
            continue
        # 同一词优先保留疾病（避免药名覆盖疾病名）
        if name in d and d[name][0] == "Disease":
            continue
        d[name] = (label, canonical)
    for w in load_base_words():
        d.setdefault(w, ("_", w))
    _DICT = d
    _MAX_LEN = max((len(w) for w in d), default=1)
    return _DICT


def entity_dict():
    """只含图谱实体的词典，供实体识别与资产导出使用。"""
    return {k: v for k, v in build_dict().items() if v[0] != "_"}


def _forward(text, dictionary, max_len):
    out, i, n = [], 0, len(text)
    while i < n:
        matched = None
        for size in range(min(max_len, n - i), 0, -1):
            piece = text[i:i + size]
            if piece in dictionary:
                matched = piece
                break
        if matched:
            out.append(matched)
            i += len(matched)
        else:
            out.append(text[i])
            i += 1
    return out


def _backward(text, dictionary, max_len):
    out, i, n = [], len(text), len(text)
    while i > 0:
        matched = None
        for size in range(min(max_len, i), 0, -1):
            piece = text[i - size:i]
            if piece in dictionary:
                matched = piece
                break
        if matched:
            out.append(matched)
            i -= len(matched)
        else:
            i -= 1
            out.append(text[i])
    return list(reversed(out))


def _score(tokens):
    """(词数, 单字词数)，越小越好。"""
    return (len(tokens), sum(1 for t in tokens if len(t) == 1))


def segment(text, dictionary=None):
    """双向最大匹配 + 启发式择优。返回 token 列表。"""
    dictionary = dictionary or build_dict()
    max_len = max((len(w) for w in dictionary), default=1)
    fwd = _forward(text, dictionary, max_len)
    bwd = _backward(text, dictionary, max_len)
    return fwd if _score(fwd) <= _score(bwd) else bwd


def find_entities(question):
    """
    在问句中识别实体，返回 [(label, canonical, surface, start, end)]。
    基础词（label="_"）不计入实体。
    """
    dictionary = build_dict()
    if not dictionary:
        return []
    tokens = segment(question, dictionary)

    found, pos = [], 0
    for tok in tokens:
        hit = dictionary.get(tok)
        if hit and hit[0] != "_":
            found.append((hit[0], hit[1], tok, pos, pos + len(tok)))
        pos += len(tok)
    return found


def pick_disease(question):
    """
    选取主实体：优先疾病实体；否则返回 (None, 0.0)。
    置信度 = 命中词长度 / 规范名长度（别名命中会低于 1），做归一化。
    """
    entities = find_entities(question)
    diseases = [e for e in entities if e[0] == "Disease"]
    if not diseases:
        return None, 0.0, entities

    # 同长度取更靠前（更符合“主语在前”的中文习惯）
    diseases.sort(key=lambda x: (-(x[4] - x[3]), x[3]))
    label, canonical, surface, start, end = diseases[0]
    ner_conf = min(1.0, len(surface) / max(2, len(canonical)))
    return canonical, round(ner_conf, 2), entities
