# MEMORY

## 项目

- 名称：基于数据挖掘的医药知识图谱问答系统（第 6 章，方案 A）
- 根目录：`D:\C\医药问答系统`
- 技术栈：Python 3.13 + FastAPI + SQLite + PyTorch（BiLSTM/TextCNN）+ matplotlib
- 提交信息：`26215150425` / 王茂麒 / 方案 A

## 关键决策

- 存储层用 SQLite 单文件替代 MongoDB + Neo4j：本机无 Docker，要求“双击可跑”；表名/字段/方向/唯一约束与原方案对齐。
- 规则优先、模型补位：词典命中精度确定，模型由模板数据训练、规模有限，只补长尾。
- 高风险分支提前到澄清之前：医学场景先劝就医。
- 模型权重、数据库、`.env` 不入提交包；`up.ps1/up.sh` 在模型缺失时自动训练。
- 证据目录 `evidence/`：验证日志、自检台账、三张截图、同步日志、备份报告。

## 失败记录（按“时间 / 操作 / 报错原文 / 根因 / 修复 / 结果”）

### 1. 2026-11-13 打包脚本路径错位

- 时间：16:58
- 操作：`pack_submission.ps1` 首次运行
- 报错原文：`New-Item : 找不到驱动器。名为 'dist...D' 的驱动器不存在`
- 根因：`$root.Path.Length` —— `$root` 是字符串，`.Path` 为 `$null`，`Substring(0)` 返回完整路径，`Join-Path` 拼出 `dist\...\D:\...`。
- 修复：改用 `$root.Length`，且 `$dst` 先 `GetFullPath`；中文名从 `submission.json` 读取，避免脚本源码编码问题。
- 结果：75 个文件打包成功。

### 2. 2026-11-13 VA10 重复节点检出为 0

- 时间：17:00
- 操作：`verify.py` 首次跑 VA10
- 报错原文：`检出={'duplicate': 0, 'orphan': 3, ...}`
- 根因：内存库是空库，只注入了 `Symptom 高血压`，不存在同名跨 Label 的第二行，构不成重复。
- 修复：`graph_doctor.inject_demo` 改为注入 `Disease 重复病X` + `Symptom 重复病X`，空库也能独立复现四类问题。
- 结果：duplicate=1、orphan=2、reverse=1、mojibake=1 全部检出。

### 3. 2026-11-13 VA10 修复后残留 1

- 时间：17:00
- 操作：同上，修复后复检
- 报错原文：`修复=5 残留=1`
- 根因：`repair` 只跑一轮；删除反向边后 `重复病X` 才变成孤立节点，而孤立清单是修复前算的。
- 修复：`repair` 改为最多 5 轮“体检 → 修复 → 复检”，直到干净。
- 结果：残留 0。

### 4. 2026-11-13 Edge 无头截图产出旧文件

- 时间：16:55 / 17:03
- 操作：`msedge --headless --screenshot`
- 报错原文：无报错，但 `demo-web.png` 大小与时间戳不变
- 根因：一是复用默认用户目录时命令被已有 Edge 实例接管；二是页面 HTML 无缓存头，旧页面被复用。
- 修复：截图使用独立 `--user-data-dir`；`/` 与 `/mobile` 响应加 `Cache-Control: no-store`；URL 加版本参数破缓存。
- 结果：三张截图正常更新，展示“正常命中 + 证据路径 + 耗时 + 回归 100%”。

### 5. 2026-11-13 PowerShell 脚本中文输出乱码

- 时间：17:00
- 操作：`verify.ps1` 运行结束打印
- 报错原文：`[verify] 鏃ュ織锛?log`
- 根因：脚本为 UTF-8 无 BOM，Windows PowerShell 5.1 按 ANSI 解析源码。
- 修复：`.ps1` 内控制台提示改为英文；中文只保留在数据与 Python 输出中。
- 结果：输出正常。

### 6. 2026-11-13 意图展示为英文标识

- 时间：17:04
- 操作：页面截图复核
- 报错原文：界面显示 `ask_drug`
- 根因：`/ask` 只返回意图 ID，前端直接展示。
- 修复：`schema.INTENT_CN` 增加 9 类中文名，响应加 `intent_cn`，前端优先展示中文。
- 结果：界面显示“用药咨询”。

## 环境事实

- 未安装 Docker；`docker --version` 报“无法将 docker 项识别为 cmdlet”。
- D:\C\python.exe 自带 torch / requests / watchdog / matplotlib；无 apscheduler（后台任务用线程实现）。
- Edge 路径：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`。
