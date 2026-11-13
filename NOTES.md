# NOTES：运行说明与已知问题

## 1. 三种启动方式

| 方式 | 命令 | 说明 |
| --- | --- | --- |
| 双击 | `启动.bat` | Windows 本地模式，自动装依赖并打开浏览器 |
| 脚本 | `./up.ps1`（Windows）/ `./up.sh`（macOS/Linux） | 启动后轮询 `/health`，就绪才返回 |
| 容器 | `docker compose up -d --wait` 或 `./up.ps1 -Docker` | 需 Docker Desktop / WSL2 后端 |

服务地址：<http://127.0.0.1:8000>；移动端壳：<http://127.0.0.1:8000/mobile>。

## 2. 验证与打分

```powershell
./verify.ps1          # 全量验证，日志写到 evidence/verify-<时间戳>.log
py -3 selfcheck.py    # 对照验收表自检，输出 evidence/self-score.csv
```

`verify.py` 覆盖：通用 V1–V8、方案 A 专属 VA1–VA12、静态 S1–S4。
Docker 相关项（V1/V2/V6、VA4 的 Cypher 可视化）在未安装 Docker 的机器上标记 SKIP，不伪造 PASS。

## 3. 训练模型（可选）

```powershell
py -3 -m models.train_all
```

- 数据由图谱自动生成：`data/train/ner_bio.txt`、`data/train/intent_train.csv`
- 产物：`models/medical_ner_cls/best_model.pt`、`metrics.jsonl`、`curves.png`
- 仅当 dev 指标创新高才覆盖模型；删除 `best_model.pt` 即自动回退规则版
- 全量训练在本机 CPU 约 1–3 分钟

## 4. 已知问题与偏离

| 项 | 说明 |
| --- | --- |
| Docker 未安装 | 本机 WSL2 未启用。管理员执行 `setup_docker.ps1` → 重启 → `./up.ps1 -Docker`；当前 V1/V2/V6 记 SKIP |
| 存储层替换 | MongoDB + Neo4j → SQLite 单文件（`medqa.db`）。表名、字段、方向、唯一约束与原方案对齐；迁 Neo4j 只需替换 `storage.py` |
| 服务数量 | 原方案四服务（mongo/neo4j/app/backup）→ 两服务（app/backup）。数据库进程被 SQLite 取代 |
| 模型选型 | 方案写 BiLSTM + TextCNN，已实现；但训练集由模板自动生成，规模有限，规则与模型是「规则优先、模型补位」的混合路由 |
| 9 类问句 | 4 类实现；另 5 类返回「待扩展 + 扩展路径」，不静默缺失、不硬凑答案 |
| 患者数据 | 仓库内无任何真实患者数据；语料均为公开科普性描述 |
| 移动端 | 提供 PWA 壳（`/mobile`，可添加到主屏），未编译原生 APK；如需 APK 可用 Capacitor 直接包裹该页 |

## 5. 仓库与备份说明

- 备份默认 `BACKUP_DRY_RUN=true`，只出包不推送；`GITHUB_REPO_URL` / `GITHUB_TOKEN` 只从环境变量读取。
- 推送使用 Deploy Key 或 PAT；本仓库不保存任何凭据。
- 备份包排除 `.env`、`*.pt`、`*.db`、`*.pyc`；命中敏感正则（`sk-`、私钥、手机号、证件号、密码赋值）即中止。
- 备份产物：`backups/backup-<时间戳>.tar.gz`；报告：`evidence/backup-report.txt`。

## 6. 验收自查（2026-11-13）

| 维度 | 自评 | 说明 |
| --- | --- | --- |
| D1 提交规范 | 见 `evidence/self-score.csv` | 目录名需按 `<编号>_<姓名>_A` 打包，见打包说明 |
| D2 环境复现 | 本地一键启动已验证；容器项未验证 | 无 Docker |
| D3 核心功能 | 采集/清洗/分词/建图/模型/问答齐备 | 模型指标见 `metrics.jsonl` |
| D4 知识库自动化 | 目录监听 + 接口 + 定时三种触发齐备 | 审核开关默认关闭 |
| D5 备份安全 | 定时 + 打包 + 排除 + 扫描 + 认证齐备 | 默认 dry run |
| D6 演示 | 网页六区块 + PWA + 移动壳 + 8 条用例 | 截图在 `evidence/` |
| D7 代码文档 | 模块分层、配置集中、方案与 NOTES 齐备 | — |
