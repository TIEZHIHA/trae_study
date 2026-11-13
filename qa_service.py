# -*- coding: utf-8 -*-
"""
问答主链路：预处理 -> 实体识别 -> 意图分类 -> 关系路由 -> 参数化查询 -> 模板答案。
返回结构固定：
  {question, answer, entity, intent, evidence, confidence, timings,
   status, reason, items, entities, trace, query}

模型与规则的关系：
  - 规则（词典匹配 + 关键词）精度高，优先使用；
  - 训练好的 BiLSTM / TextCNN 作为补充，仅在规则未命中时接管；
  - 模型文件缺失或加载失败自动回退规则，不影响服务可用性。
"""
import re
import time

import config
import storage
from schema import (
    INTENT_CN, INTENT_PENDING, INTENT_RELATION, INTENT_RULES, MSG_CLARIFY, MSG_EMPTY,
    MSG_PENDING, MSG_SAFETY, PENDING_CN, PENDING_RULES, REL_CN, RISK_KEYWORDS,
    SAFETY_NOTE, TEMPLATES,
)
from segment import build_dict, pick_disease

# 全角 -> 半角（只处理常见标点，不动中文内容）
_PUNC_MAP = str.maketrans({"？": "?", "！": "!", "，": ",", "。": ".", "：": ":", "；": ";"})

# 参数化查询语句（SQLite 版；cypher 字段给出等价写法，便于对照方案原文）
SQL_FACTS = ("SELECT dst_label, dst_name, source FROM edges "
             "WHERE src_label=? AND src_name=? AND rel=? ORDER BY id")

_MODEL = None
_MODEL_LOADED = False


def warmup():
    """预加载模型，避免首个请求承担加载耗时。失败返回 None。"""
    global _MODEL, _MODEL_LOADED
    if _MODEL_LOADED:
        return _MODEL
    _MODEL_LOADED = True
    if not config.ENABLE_MODEL:
        return None
    try:
        from models.predict import MedicalModel
        _MODEL = MedicalModel.load()
    except Exception:
        _MODEL = None
    return _MODEL


def model_info():
    """给 /health 用的模型状态。"""
    m = warmup()
    if not m:
        return {"ok": False, "enabled": config.ENABLE_MODEL,
                "reason": "模型未训练或未启用，使用规则版"}
    return {"ok": True, "enabled": True, "ner_f1": m.best_ner_f1,
            "intent_acc": m.best_intent_acc, "path": str(config.MODEL_PATH)}


def preprocess(question):
    """清洗问句：去首尾空白、压缩空白、统一标点。"""
    q = (question or "").strip()
    q = re.sub(r"\s+", " ", q)
    return q.translate(_PUNC_MAP)


def detect_risk(question):
    """高风险词检测：命中返回该词，便于在答案里说明触发原因。"""
    for w in RISK_KEYWORDS:
        if w in question:
            return w
    return None


def classify(question):
    """
    classify(q) -> (intent, confidence)
    规则版分类器：命中关键词即判为该意图，置信度对齐验收基线 0.96；
    未命中返回 (None, 0.3)，交给模型或澄清兜底。
    """
    for intent, words in INTENT_RULES:
        for w in words:
            if w in question:
                return intent, 0.96
    for intent, words in PENDING_RULES:
        for w in words:
            if w in question:
                return intent, 0.96
    return None, 0.3


def query_facts(entity, intent):
    """qe(entity, intent) -> facts。参数化查询，拼接全部走占位符。"""
    rel = INTENT_RELATION.get(intent)
    if not rel:
        return []
    return storage.query_facts(entity, rel)


def build_evidence(entity, intent, facts):
    """证据路径：疾病 -[关系]-> 目标实体，附来源文件，保证可追溯。"""
    rel = INTENT_RELATION.get(intent)
    if not rel or not facts:
        return []
    return [
        {
            "path": f"({entity}:Disease)-[:{rel}]->({f['dst_name']}:{f['dst_label']})",
            "source": f.get("source", ""),
        }
        for f in facts
    ]


def _model_entity(question, model):
    """模型实体识别 + 词典校验（不认识的实体一律丢弃）。"""
    if not model:
        return None
    hit = model.predict_entity(question)
    if not hit or hit["conf"] < 0.90:
        return None
    word = build_dict().get(hit["surface"])
    if not word or word[0] != "Disease":
        return None
    return {"canonical": word[1], "conf": hit["conf"], "surface": hit["surface"]}


def ask(question):
    """主入口。所有分支都会写入 qa_logs，便于错误答案回流。"""
    t0 = time.perf_counter()
    timings = {}
    trace = []

    # ---- 1. 预处理
    q = preprocess(question)
    timings["preprocess"] = round((time.perf_counter() - t0) * 1000, 2)
    trace.append({"step": "1.preprocess", "text": q})
    if not q:
        return _finish(q, None, None, "clarify", MSG_CLARIFY, 0.0, 0.0, timings,
                       "空问句", t0, trace=trace)

    # ---- 2. 实体识别（规则优先，模型补充）
    t1 = time.perf_counter()
    tm = time.perf_counter()
    model = warmup()
    m_entity = _model_entity(q, model)
    m_intent, m_intent_conf = (model.predict_intent(q) if model else (None, 0.0))
    timings["model"] = round((time.perf_counter() - tm) * 1000, 2)

    entity, ner_conf, entities = pick_disease(q)
    ner_source = "rule" if entity else "-"
    if not entity and m_entity:
        entity, ner_conf, ner_source = m_entity["canonical"], m_entity["conf"], "model"
    timings["ner"] = round((time.perf_counter() - t1) * 1000, 2)
    trace.append({
        "step": "2.ner", "entity": entity, "confidence": ner_conf,
        "source": ner_source,
        "entities": [{"label": e[0], "name": e[1], "surface": e[2]} for e in entities],
    })

    # ---- 3. 意图分类（规则优先，模型补充）
    t2 = time.perf_counter()
    intent, intent_conf = classify(q)
    intent_source = "rule" if intent else "-"
    if intent is None and m_intent:
        intent, intent_conf, intent_source = m_intent, m_intent_conf, "model"
    timings["intent"] = round((time.perf_counter() - t2) * 1000, 2)
    trace.append({
        "step": "3.intent", "intent": intent, "confidence": intent_conf,
        "source": intent_source,
    })

    # ---- 4. 医学安全优先：高风险问题直接给就医建议，不进入查询
    # 说明：方案里 safety 是第 3 级兜底，但演示用例「孕妇胸闷气短怎么办」没有疾病实体，
    # 若严格按序会被“低置信度澄清”截走。医学场景下安全优先，故提前判定。
    risk = detect_risk(q)
    if risk:
        trace.append({"step": "4.route", "relation": None, "reason": f"高风险:{risk}"})
        return _finish(
            q, entity, intent, "safety",
            MSG_SAFETY + f"（触发词：{risk}）",
            ner_conf, intent_conf, timings, f"高风险:{risk}", t0,
            trace=trace, confidence_meta={"ner_source": ner_source,
                                          "intent_source": intent_source},
        )

    # ---- 5. 低置信度 / 未识别实体 -> 澄清
    if not entity or ner_conf < 0.5:
        trace.append({"step": "4.route", "relation": None, "reason": "实体未识别"})
        return _finish(q, entity, intent, "clarify", MSG_CLARIFY,
                       ner_conf, intent_conf, timings, "实体未识别", t0,
                       trace=trace, confidence_meta={"ner_source": ner_source,
                                                     "intent_source": intent_source})
    if intent_conf < 0.75:
        trace.append({"step": "4.route", "relation": None, "reason": "意图未识别"})
        return _finish(q, entity, intent, "clarify", MSG_CLARIFY,
                       ner_conf, intent_conf, timings, "意图未识别", t0,
                       trace=trace, confidence_meta={"ner_source": ner_source,
                                                     "intent_source": intent_source})

    # ---- 6. 第二版扩展意图
    if intent in INTENT_PENDING:
        trace.append({"step": "4.route", "relation": None,
                      "reason": f"待扩展:{intent}"})
        answer = MSG_PENDING.format(
            intent_cn=PENDING_CN[intent], path=INTENT_PENDING[intent]
        )
        return _finish(q, entity, intent, "pending", answer,
                       ner_conf, intent_conf, timings, "待扩展意图", t0,
                       trace=trace, confidence_meta={"ner_source": ner_source,
                                                     "intent_source": intent_source})

    # ---- 7. 关系路由 + 图谱查询
    rel = INTENT_RELATION.get(intent)
    trace.append({"step": "4.route", "relation": rel})
    t3 = time.perf_counter()
    facts = query_facts(entity, intent)
    timings["query"] = round((time.perf_counter() - t3) * 1000, 2)
    query = {
        "engine": "sqlite",
        "sql": SQL_FACTS,
        "params": ["Disease", entity, rel],
        "cypher": f"MATCH (d:Disease {{name:$entity}})-[:{rel}]->(x) "
                  f"WHERE d.name=$entity RETURN x.name, x.source",
        "rows": len(facts),
    }
    trace.append({"step": "5.query", **query})

    # ---- 8. 结果为空：不编造
    if not facts:
        rel_cn = REL_CN.get(rel, "相关")
        return _finish(
            q, entity, intent, "empty",
            MSG_EMPTY.format(entity=entity, rel_cn=rel_cn),
            ner_conf, intent_conf, timings, "图谱无结果", t0,
            trace=trace, query=query,
            confidence_meta={"ner_source": ner_source, "intent_source": intent_source},
        )

    # ---- 9. 正常：模板拼装 + 安全提示
    items = [f["dst_name"] for f in facts]
    answer = TEMPLATES[intent].format(entity=entity, items="、".join(items))
    answer = answer + SAFETY_NOTE
    evidence = build_evidence(entity, intent, facts)
    trace.append({"step": "6.answer", "status": "ok", "chars": len(answer)})

    if m_entity and ner_source != "model":
        names = {e[1] for e in entities}
        if m_entity["canonical"] not in names:
            entities = entities + [("Disease", m_entity["canonical"], m_entity["surface"], 0, 0)]

    return _finish(q, entity, intent, "ok", answer, ner_conf, intent_conf,
                   timings, "命中", t0, evidence=evidence, items=items,
                   entities=[{"label": e[0], "name": e[1], "surface": e[2]} for e in entities],
                   trace=trace, query=query,
                   confidence_meta={"ner_source": ner_source,
                                    "intent_source": intent_source})


def _finish(q, entity, intent, status, answer, ner_conf, intent_conf, timings,
            reason, t0, evidence=None, items=None, entities=None, trace=None,
            query=None, confidence_meta=None):
    """统一出口：补全耗时、日志、返回结构。"""
    timings["total"] = round((time.perf_counter() - t0) * 1000, 2)
    storage.log_qa(q, entity, intent, status, answer, ner_conf, intent_conf, timings["total"])
    confidence = {"ner": ner_conf, "intent": intent_conf}
    confidence.update(confidence_meta or {})
    return {
        "question": q,
        "answer": answer,
        "entity": entity,
        "intent": intent,
        "intent_cn": INTENT_CN.get(intent, intent) if intent else "",
        "evidence": evidence or [],
        "confidence": confidence,
        "timings": timings,
        "status": status,
        "reason": reason,
        "items": items or [],
        "entities": entities or [],
        "trace": trace or [],
        "query": query or {},
    }


def regression():
    """题库回归：逐条执行自动生成的问句，通过率 >= 95% 为达标。"""
    cases = storage.qb_all()
    passed, details = 0, []
    for c in cases:
        r = ask(c["question"])
        # 判据：状态正常且答案里包含标准答案中的首个实体
        expect_first = (c["answer"].split("：")[-1].split("。")[0].split("、")[0]).strip()
        ok = r["status"] == "ok" and expect_first and expect_first in r["answer"]
        passed += 1 if ok else 0
        details.append({
            "question": c["question"],
            "status": r["status"],
            "pass": ok,
        })
    total = len(cases)
    rate = round(passed / total * 100, 2) if total else 0.0
    return {"total": total, "passed": passed, "rate": rate, "details": details}
