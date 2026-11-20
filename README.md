# 医药知识图谱问答系统

第 6 章《基于数据挖掘的医药问答系统》的可运行工程。主线是 **数据挖掘 → 知识图谱 → 智能问答**：
语料经清洗抽取成三元组进入图谱，提问经实体识别与意图分类后转成参数化查询，答案由模板拼装，不编造。

## 快速开始

```powershell
./up.ps1            # Windows；macOS/Linux 用 ./up.sh
```

或双击 `启动.bat`，浏览器打开 <http://127.0.0.1:8000>；移动端壳 <http://127.0.0.1:8000/mobile>。

容器：`docker compose up -d --wait`（需 Docker Desktop / WSL2）。

## 运行链路

```
data/inbox/*.md + 网页采集
  → clean.parse_document        清洗与解析（六字段）
  → build_graph.extract_triples 实体与关系抽取
  → storage.merge_node/edge     MERGE 入图（label+name 唯一）
  → kb.question_bank            自动生成问句 + 标准答案
  → resources.export_all        词典 / 实体表 / 关系候选表 / 训练集

用户提问
  → qa_service.preprocess       预处理
  → segment.pick_disease        双向最大匹配 + 启发式择优
  → qa_service.classify         规则意图（5 类实现 + 5 类待扩展）
  → models.predict              规则未命中时由 BiLSTM / TextCNN 补位
  → storage.query_facts         参数化查询（症状驱动走反向查询）
  → schema.TEMPLATES            模板答案 + 安全提示
```

症状驱动的反向查询：输入「咳嗽怎么办」时，先由 `storage.diseases_by_symptom`
反查可能疾病，再取这些疾病的用药与预防，按「疾病 → 药物 → 护理」分段回答。

口语同义词（如「头疼」→「头痛」、「心慌」→「心悸」）定义在 `schema.SYMPTOM_ALIASES`，
启动时由 `storage.ensure_symptom_aliases` 写入症状节点的 alias 字段，随词典一起参与实体识别；
规范名在图谱中不存在的别名会被跳过，不会凭空造节点。

## 四级兜底

| 级别 | 触发条件 | 行为 |
| --- | --- | --- |
| 空结果 | 图谱无对应关系 | 明确说明无记录，不做推测 |
| 低置信度 | 未识别实体 / 意图置信度不足 | 请用户补充具体疾病名 |
| 高风险 | 命中孕妇、胸闷、昏迷等词 | 建议立即就医，不给用药建议 |
| 待扩展 | 命中第二版意图（相互作用等） | 说明未开放及扩展路径 |

安全分支优先于澄清分支：医学场景下“先劝就医”比“先追问”更重要。

## 常用命令

```powershell
py -3 GUI.py                          # 启动服务
py -3 -m models.train_all             # 训练 NER + 意图并导出资产
py -3 -m models.train --ner-epochs 30 # 只训练
py -3 verify.py                       # 验收对照验证（V1–V8 / VA1–VA12 / S1–S4）
py -3 selfcheck.py                    # 对照打分表自检，输出 evidence/self-score.csv
./pack_submission.ps1                 # 打包 dist/<编号>_<姓名>_A（排除权重/数据库/.env）
py -3 -m backup.daemon                # 独立备份守护（容器里用）
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 演示页（支持 `?q=问句` 直接演示） |
| GET | `/mobile` | 移动端 APP 壳 |
| GET | `/health` | 组件健康（sqlite/图谱/模型/后台任务） |
| POST | `/ask` | 问答主接口，返回答案、证据、trace、耗时 |
| GET | `/demo/cases` | 8 条演示用例 |
| GET/POST | `/admin/kb/stats`、`/admin/kb/sync` | 知识库统计 / 立即同步 |
| GET/POST | `/admin/kb/pending`、`/admin/kb/approve` | 审核队列 / 审核通过 |
| GET | `/admin/regression` | 题库回归 |
| POST/GET | `/admin/backup/run`、`/admin/backup/status` | 备份 / 状态 |
| GET | `/admin/scheduler/status` | 目录监听与定时任务状态 |
| GET | `/admin/logs?limit=20` | 最近问答 |

## 知识库语料

```markdown
# 疾病名

别名：别名1、别名2
简介：一句话描述

## 药物
- 药品名
```

`## 症状 / ## 检查 / ## 预防` 同理。丢进 `data/inbox/` 后 1.5 秒内被目录监听捕获；重复投放不重复入图（`doc_id=sha256(相对路径+内容)`）。

同一文件内容变更时按路径识别为新版本：旧版本登记与清洗记录被删除，图谱按 `clean_kb` 全量重建，
旧关系不会残留（同步详情里状态为 `updated`），历史版本不会在 `clean_kb` 里越攒越多。

审核模式：`KB_REQUIRE_REVIEW=true` 时先入 `pending_kb`，调用 `/admin/kb/approve` 才进图谱。

## 备份与安全

- 默认 `BACKUP_DRY_RUN=true`，只出包不推送；`GITHUB_REPO_URL` / `GITHUB_TOKEN` 只从环境变量读取。
- 包内：配置、源码、词典、语料、题库导出、脱敏日志摘要；排除 `.env`、`*.pt`、`*.db`。
- 备份前扫描 `sk-`、私钥、手机号、身份证、密码赋值，命中即中止。
- 仓库不含任何真实患者数据。

## 与方案原文的偏离

方案原设计为 Docker + MongoDB + Neo4j + 四服务。本机未安装 Docker，存储层改为 **SQLite 单文件**（表名、字段、关系方向、唯一约束对齐原方案），compose 精简为 app + backup 两个服务。
问答链路、9 类意图、四级兜底、题库回归、备份与验证脚本保持不变；迁 Neo4j 只需替换 `storage.py`。

> 答案均来自知识图谱既有记录，仅供健康科普参考，不能替代医生面诊与处方。
