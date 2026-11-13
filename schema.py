# -*- coding: utf-8 -*-
"""
Schema 与命名常量：关系名、Label、意图、模板的唯一来源。
方案要求：方向统一 Disease -> 目标实体，禁止在代码里写死关系名。
"""

# ------------------------- 五类节点 Label -------------------------
DISEASE = "Disease"
DRUG = "Drug"
SYMPTOM = "Symptom"
CHECK = "Check"
PREVENT = "Prevent"

# ------------------------- 关系名 -------------------------
HAS_DRUG = "HAS_DRUG"
HAS_SYMPTOM = "HAS_SYMPTOM"
NEED_CHECK = "NEED_CHECK"
PREVENTS = "PREVENTS"
ALIAS_OF = "ALIAS_OF"

# 字段 -> (目标Label, 关系名)。建图时按这张表循环，新增关系只改这里。
FIELD_RELATION = {
    "drug": (DRUG, HAS_DRUG),
    "symptom": (SYMPTOM, HAS_SYMPTOM),
    "check": (CHECK, NEED_CHECK),
    "prevent": (PREVENT, PREVENTS),
}

# 关系 -> 中文名，用于证据路径展示
REL_CN = {
    HAS_DRUG: "用药",
    HAS_SYMPTOM: "症状",
    NEED_CHECK: "检查",
    PREVENTS: "预防",
    ALIAS_OF: "别名",
}

# ------------------------- 9 类问句 -> 意图 -------------------------
# 第一版实现 4 类；其余 5 类明确标注“待扩展”，不靠模板硬凑。
INTENT_ASK_DRUG = "ask_drug"
INTENT_ASK_SYMPTOM = "ask_symptom"
INTENT_ASK_CHECK = "ask_check"
INTENT_ASK_PREVENT = "ask_prevent"

# 待扩展意图（给出扩展路径，不静默缺失）
INTENT_PENDING = {
    "ask_interaction": "需新增 Drug-Drug 关系与禁忌属性",
    "ask_possible_disease": "需 Symptom -> Disease 反向查询与多跳路径",
    "ask_treatment_plan": "需疾病节点新增 plan 属性",
    "ask_cycle": "需疾病节点新增 cycle 属性",
    "ask_symptom_desc": "需症状节点新增 desc / severity 属性",
}

# 意图 -> 关系（第一版 4 类）
INTENT_RELATION = {
    INTENT_ASK_DRUG: HAS_DRUG,
    INTENT_ASK_SYMPTOM: HAS_SYMPTOM,
    INTENT_ASK_CHECK: NEED_CHECK,
    INTENT_ASK_PREVENT: PREVENTS,
}

# ------------------------- 意图关键词规则 -------------------------
# 顺序敏感：先匹配更具体的意图，避免「怎么预防」被判成「用药」。
INTENT_RULES = [
    (INTENT_ASK_PREVENT, ["预防", "怎么防", "如何防", "避免", "要注意什么", "注意什么"]),
    (INTENT_ASK_CHECK, ["检查", "化验", "查什么", "做什么检测", "诊断方法"]),
    (INTENT_ASK_SYMPTOM, ["症状", "表现", "有哪些不适", "什么感觉"]),
    (INTENT_ASK_DRUG, ["吃什么药", "用药", "药物", "药品", "吃什么", "开什么药", "用什么药"]),
]

# 第二版扩展意图的识别关键词：命中后明确回复“待扩展 + 扩展路径”，不硬凑答案
PENDING_RULES = [
    ("ask_interaction", ["相互作用", "一起吃", "同服", "能一起用", "冲突"]),
    ("ask_possible_disease", ["可能是什么病", "会得什么病", "并发症", "会不会是"]),
    ("ask_treatment_plan", ["治疗方案", "怎么治疗", "如何治疗", "治疗办法"]),
    ("ask_cycle", ["治疗周期", "多久能好", "要治多久", "疗程"]),
    ("ask_symptom_desc", ["症状描述", "具体表现是什么样", "严重程度"]),
]

# ------------------------- 高风险问句关键词 -------------------------
# 命中即走“建议及时就医”兜底，优先级最高。
RISK_KEYWORDS = [
    "孕妇", "怀孕", "哺乳", "婴儿", "新生儿", "儿童",
    "胸痛", "胸闷", "呼吸困难", "昏迷", "抽搐", "大出血",
    "自杀", "中毒", "休克", "剧烈腹痛", "高烧不退",
]

# ------------------------- 答案模板 -------------------------
# 模板只做拼装，不生成医学结论，不编造。
TEMPLATES = {
    INTENT_ASK_DRUG: "关于「{entity}」，知识图谱中记录的常用药物有：{items}。",
    INTENT_ASK_SYMPTOM: "「{entity}」在图谱中记录的常见症状包括：{items}。",
    INTENT_ASK_CHECK: "「{entity}」通常需要做的检查有：{items}。",
    INTENT_ASK_PREVENT: "针对「{entity}」，可参考的预防措施有：{items}。",
}

# 安全提示：每条答案必带
SAFETY_NOTE = "以上内容来自知识图谱的既有记录，仅供健康科普参考，不能替代医生面诊与处方。"

# 四类兜底文案
MSG_EMPTY = "知识图谱中未查询到与「{entity}」相关的{rel_cn}信息，暂不提供推测性回答。"
MSG_CLARIFY = "没能准确识别您问的疾病或问题类型，请补充具体疾病名称，例如“风热感冒吃什么药”。"
MSG_SAFETY = "该问题涉及较高健康风险，建议立即前往医院就诊或拨打急救电话，本系统不做自行用药建议。"
MSG_PENDING = "「{intent_cn}」属于第二版扩展能力，当前版本暂未开放。扩展路径：{path}。"

# 待扩展意图的中文名
PENDING_CN = {
    "ask_interaction": "药物相互作用",
    "ask_possible_disease": "可能疾病",
    "ask_treatment_plan": "治疗方案",
    "ask_cycle": "治疗周期",
    "ask_symptom_desc": "症状细化说明",
}

# 全部 9 类意图的中文名（前端展示用）
INTENT_CN = {
    "ask_drug": "用药咨询",
    "ask_symptom": "症状咨询",
    "ask_check": "检查咨询",
    "ask_prevent": "预防咨询",
    **PENDING_CN,
}
