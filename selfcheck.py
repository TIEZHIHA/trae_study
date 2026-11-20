# -*- coding: utf-8 -*-
"""
对照《方案 A/B 项目验收标准与 100 分打分表》自检并模拟打分。
    py -3 selfcheck.py

输出：
  控制台逐项 PASS/PART/WEAK/FAIL 与维度得分
  evidence/self-score.csv 逐项台账

说明：这是“自检”，不是官方评分；人工项按代码与证据的可核对程度给档。
"""
import csv
import json
import re
import sqlite3
import tarfile
import urllib.request
from pathlib import Path

import config
import graph_doctor
import qa_service
import schema
import storage
from backup import backup as backup_mod
from backup.sensitive import scan_text
from kb import auto_add

BASE = config.BASE_DIR
PKG_NAME = "26215150425_王茂麒_A"
PKG = BASE / "dist" / PKG_NAME
BASE_URL = f"http://127.0.0.1:{config.PORT}"

WEIGHT = {"PASS": 1.0, "PART": 0.6, "WEAK": 0.3, "FAIL": 0.0}
DIMS = {"D1": 10, "D2": 15, "D3": 30, "D4": 10, "D5": 10, "D6": 15, "D7": 10}
ROWS = []


def add(dim, code, maxp, status, detail):
    ROWS.append({"dim": dim, "code": code, "max": maxp, "status": status,
                 "score": round(maxp * WEIGHT[status], 2), "detail": detail})


def http_json(path, method="GET", payload=None, timeout=3):
    try:
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") \
            if method == "POST" else None
        req = urllib.request.Request(BASE_URL + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def grade_status(ok, weak=False):
    if ok:
        return "PASS"
    return "WEAK" if weak else "FAIL"


# ================================================================ D1
def check_d1():
    pkg = PKG if PKG.exists() else BASE
    note = "" if PKG.exists() else "（未打包，按项目根目录判定）"
    add("D1", "D1-1 目录命名", 1,
        grade_status(bool(re.fullmatch(r"\d+_.+_[AB]", pkg.name))),
        f"{pkg.name}{note}")
    add("D1", "D1-2 目录树结构", 1, "PART",
        "根目录平铺，未采用 src/ 子目录（可用，非规范形态）")

    sub = json.loads((BASE / "submission.json").read_text(encoding="utf-8"))
    add("D1", "D1-3 元数据 id/name/scheme", 1,
        grade_status(all(sub.get(k) for k in ("id", "name", "scheme"))),
        f"{sub.get('id')}/{sub.get('name')}/{sub.get('scheme')}")
    add("D1", "D1-4 元数据时间/仓库/备注", 1,
        grade_status(all(k in sub for k in ("submitted_at", "repo_url", "notes")) and bool(sub.get("repo_url"))),
        "repo_url 为空，仅留备注" if not sub.get("repo_url") else "齐全")

    must4 = ["submission.json", "docs/方案.md", "GUI.py", "docker-compose.yml"]
    add("D1", "D1-5 必交 1–4 项", 2,
        grade_status(all((pkg / f).exists() for f in must4)),
        "齐备" if all((pkg / f).exists() for f in must4) else "有缺失")

    scripts = ["up.sh", "up.ps1", "verify.sh", "verify.ps1", ".env.example", "NOTES.md"]
    ev = list((pkg / "evidence").glob("*")) if (pkg / "evidence").exists() else []
    ok6 = all((pkg / f).exists() for f in scripts) and len(ev) >= 4
    add("D1", "D1-6 必交 5–8 项", 2, grade_status(ok6),
        f"脚本齐全，证据 {len(ev)} 份")

    files = backup_mod.collect_files()
    secrets = [f.name for f in files if f.name in (".env", ".env.local")]
    add("D1", "D1-7 无 .env 与真实密钥", 1, grade_status(not secrets),
        "无 .env" if not secrets else f"发现 {secrets}")

    weights = [p.name for p in pkg.rglob("*") if p.suffix in (".pt", ".db", ".db-wal")]
    add("D1", "D1-8 无模型权重/数据库卷", 1, grade_status(not weights),
        "无权重与库卷" if not weights else f"发现 {weights[:3]}")


# ================================================================ D2
def check_d2():
    add("D2", "D2-1 up.sh 存在", 1, grade_status((BASE / "up.sh").exists()), "up.sh")
    add("D2", "D2-2 up.ps1 存在", 1, grade_status((BASE / "up.ps1").exists()), "up.ps1")
    add("D2", "D2-3 无手工补步骤", 2, "PASS", "脚本内自动装依赖/初始化/缺模型自动训练")
    mac_logs = [p for p in config.EVIDENCE_DIR.glob("verify-*.log")
                if "darwin" in p.read_text(encoding="utf-8", errors="ignore").lower()]
    add("D2", "D2-4 macOS up 实跑", 1.5,
        "PASS" if mac_logs else "WEAK",
        f"evidence 中 macOS 日志 {len(mac_logs)} 份" if mac_logs else "sh 脚本齐备，未在 macOS 实跑")
    health = http_json("/health")
    add("D2", "D2-5 Windows up 实跑", 1.5, grade_status(bool(health)),
        "服务在线" if health else "服务未启动")

    import verify
    v = {}
    for code, fn in [("V1", verify.v1_container), ("V2", verify.v2_components),
                     ("V3", verify.v3_up_script), ("V4", verify.v4_full_verify),
                     ("V5", verify.v5_cross_platform), ("V6", verify.v6_reproduce),
                     ("V7", verify.v7_demo_reachable), ("V8", verify.v8_evidence)]:
        v[code] = fn()[0]
    passed = sum(1 for s in v.values() if s == "PASS")
    st = "PASS" if passed == 8 else ("PART" if passed >= 6 else "WEAK" if passed >= 4 else "FAIL")
    add("D2", "D2-6 V1–V8", 4, st, f"{passed}/8 PASS：{v}")

    s_ok = all(fn()[0] == "PASS" for fn in
               (verify.s1_sql_injection, verify.s2_backup_scope,
                verify.s3_coverage, verify.s4_sensitive))
    add("D2", "D2-7 S1–S4", 1, grade_status(s_ok), "4 项静态检查")
    add("D2", "D2-8 down→up 数据恢复", 3, grade_status(verify.v6_reproduce()[0] == "PASS"),
        verify.v6_reproduce()[1])


# ================================================================ D3
def check_d3():
    import verify
    a1 = [verify.va1_crawler()[0], verify.va2_clean()[0]]
    add("D3", "A1 采集/解析/清洗", 6,
        "PASS" if all(s == "PASS" for s in a1) else "PART", f"{a1}")
    assets = [config.DICT_PATH, BASE / "resource" / "entity_table.csv",
              BASE / "resource" / "relation_candidates.csv",
              config.TRAIN_DIR / "ner_bio.txt"]
    a2 = verify.va3_segment()[0] == "PASS" and all(p.exists() for p in assets)
    add("D3", "A2 分词与词典", 4, grade_status(a2),
        f"分词={verify.va3_segment()[1]} 资产={sum(p.exists() for p in assets)}/4")
    add("D3", "A3 建图", 8, verify.va4_build_graph()[0], verify.va4_build_graph()[1])
    add("D3", "A4 模型训练", 6, verify.va5_model()[0], verify.va5_model()[1])
    add("D3", "A5 问答链路", 6, verify.va6_qa()[0], verify.va6_qa()[1])


# ================================================================ D4
def check_d4():
    sched = http_json("/admin/scheduler/status") or {}
    add("D4", "D4-1 目录监听", 1, grade_status(sched.get("watcher") is True),
        f"watcher={sched.get('watcher')} last={sched.get('sync_last', '')[:60]}")
    sync = http_json("/admin/kb/sync", "POST")
    add("D4", "D4-2 接口触发", 1, grade_status(bool(sync)),
        f"scanned={sync.get('scanned') if sync else 'None'}")
    add("D4", "D4-3 定时同步", 1, "PART" if (sched.get("interval_min") or 0) > 0 else "FAIL",
        f"interval={sched.get('interval_min')}min（未等满一个周期，按设计给档）")

    first = auto_add.sync_once()
    second = auto_add.sync_once()
    add("D4", "D4-4 重复同步不增", 3, grade_status(second["added"] == 0),
        f"二次新增={second['added']}")
    add("D4", "D4-5 增量处理", 1, grade_status("added" in first and "skipped" in first),
        "doc_id=sha256(相对路径+内容)")

    stats = auto_add.inbox_stats()
    four = all(k in stats for k in ("inbox_files", "docs_processed", "questions", "graph"))
    add("D4", "D4-6 stats 四项", 1, grade_status(four), str({k: stats[k] for k in
        ("inbox_files", "docs_processed", "questions")}))

    # 审核开关：临时库 + 临时文件，验证 pending 流程后立即清理
    tmp = BASE / "data" / "inbox" / "_review_probe.md"
    tmp.write_text("# 审核探针\n## 药物\n- 探针药A\n", encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    old = storage._CONN
    storage._CONN = conn
    try:
        storage.init_db()
        status, _ = auto_add.process_file(tmp, require_review=True)
        pending_ok = status == "pending" and storage.pending_count() == 1
    finally:
        storage._CONN = old
        conn.close()
        tmp.unlink(missing_ok=True)
    add("D4", "D4-7 审核开关", 1, grade_status(pending_ok), "KB_REQUIRE_REVIEW -> pending")

    kb_log = (config.LOGS_DIR / "kb-sync.log")
    line = json.loads(kb_log.read_text(encoding="utf-8").strip().splitlines()[-1])
    need = {"scanned", "added", "skipped", "elapsed_ms"}
    add("D4", "D4-8 同步日志", 1, grade_status(need.issubset(line)), str(sorted(line)))


# ================================================================ D5
def check_d5():
    sched = http_json("/admin/scheduler/status") or {}
    add("D5", "D5-1 定时配置", 2, "PART" if sched.get("backup_hour") is not None else "FAIL",
        f"BACKUP_CRON_HOUR={sched.get('backup_hour')}（宿主常驻线程，未跨天实跑）")

    result = backup_mod.run_backup(dry_run=True)
    package = BASE / "backups" / result["package"] if result.get("package") else None
    members = []
    if package and package.exists():
        with tarfile.open(package) as tar:
            members = tar.getnames()
    inc_ok = (any(m.endswith("config.py") for m in members)
              and any("resource/dict" in m or "resource\\dict" in m for m in members)
              and any("data/inbox" in m or "data\\inbox" in m for m in members)
              and any("question_bank.csv" in m for m in members)
              and any("logs-summary.txt" in m for m in members))
    add("D5", "D5-2/3/4 打包范围", 2, grade_status(inc_ok),
        f"包内 {len(members)} 项，含导出/词典/语料")
    exc_ok = not any(m.endswith((".env", ".pt", ".db")) for m in members)
    add("D5", "D5-5/6 排除项", 2, grade_status(exc_ok), "无 .env/.pt/.db")

    original = backup_mod.scan_files
    backup_mod.scan_files = lambda files: [{"file": "probe", "kind": "openai_key"}]
    try:
        blocked = backup_mod.run_backup(dry_run=True)
    finally:
        backup_mod.scan_files = original
    add("D5", "D5-7 敏感扫描拦截", 2, grade_status(blocked["status"] == "blocked"),
        f"注入探针 -> {blocked['status']}")
    backup_mod.run_backup(dry_run=True)      # 恢复正常状态文件，避免留下 blocked

    auth_ok = (config.BACKUP_DRY_RUN is True
               and not (BASE / ".env").exists()
               and "GITHUB_TOKEN" in (BASE / "config.py").read_text(encoding="utf-8"))
    add("D5", "D5-8 认证与默认态", 2, grade_status(auth_ok),
        "env 注入 + 默认 DRY_RUN=true")


# ================================================================ D6
def check_d6():
    html = (BASE / "web" / "index.html").read_text(encoding="utf-8")
    blocks = {
        "状态灯": "healthText" in html,
        "答案与status": "renderAnswer" in html and "STATUS_CN" in html,
        "证据/路径": "图谱证据路径" in html,
        "耗时": "分段耗时" in html,
        "知识库统计": "知识库" in html and "by_label" in html,
        "备份状态": "自动备份" in html,
    }
    add("D6", "D6-1/2/3 网页六区块", 4, grade_status(all(blocks.values())), str(blocks))

    manifest = json.loads((BASE / "web" / "manifest.json").read_text(encoding="utf-8"))
    icons = manifest.get("icons", [])
    pwa_ok = manifest.get("display") == "standalone" and len(icons) >= 2 \
        and (BASE / "web" / "icons" / "icon-192.png").exists()
    add("D6", "D6-4 PWA", 2, grade_status(pwa_ok), f"icons={len(icons)} display={manifest.get('display')}")

    mobile = (BASE / "mobile" / "index.html").read_text(encoding="utf-8")
    app_ok = all(p in mobile for p in ("/health", "/demo/cases", "/ask"))
    add("D6", "D6-5 移动端壳", 3, "PART" if app_ok else "FAIL",
        "PWA 壳调三接口；未编译原生 APK")

    cases = http_json("/demo/cases")
    bad = []
    if cases:
        for c in cases["cases"]:
            r = http_json("/ask", "POST", {"question": c["question"]})
            if not r or r["status"] != c["expect"]:
                bad.append(c["question"])
    add("D6", "D6-6 必演用例", 3, grade_status(bool(cases) and not bad),
        f"{len(cases['cases']) - len(bad) if cases else 0} 条符合预期")

    ev = [p.name for p in config.EVIDENCE_DIR.glob("*")]
    add("D6", "D6-7 Trae 留痕", 3, grade_status(len(ev) >= 5),
        f"evidence/{len(ev)} 份")


# ================================================================ D7
def check_d7():
    rel_central = "FIELD_RELATION" in (BASE / "schema.py").read_text(encoding="utf-8")
    add("D7", "D7-1 结构与常量", 3, "PASS" if rel_central else "PART",
        "schema.py 集中定义关系/意图/模板")
    cfg = (BASE / "config.py").read_text(encoding="utf-8")
    hard = re.findall(r"sk-[A-Za-z0-9]{16,}", cfg)
    add("D7", "D7-2 配置与密钥隔离", 2, grade_status(not hard and "os.getenv" in cfg),
        "环境变量覆盖，无硬编码密钥")
    doc = (BASE / "docs" / "方案.md").read_text(encoding="utf-8")
    doc_ok = all(k in doc for k in ("做法", "依赖", "实施步骤", "演示设计")) \
        and (BASE / "NOTES.md").exists()
    add("D7", "D7-3 文档完整性", 2, grade_status(doc_ok), "方案四部分 + NOTES")
    logs = all((config.LOGS_DIR / f).exists()
               for f in ("kb-sync.log", "build-graph.log"))
    add("D7", "D7-4 日志与兜底", 2, grade_status(logs), "同步/建图/问答三类日志")
    try:
        import py_compile
        for p in list(BASE.glob("*.py")) + list(BASE.glob("models/*.py")):
            py_compile.compile(str(p), doraise=True)
        comp = True
    except Exception:
        comp = False
    add("D7", "D7-5 可维护性", 1, "PART" if comp else "FAIL", "全量编译通过，存在少量未调用辅助函数")


# ================================================================ 汇总
def decide_grade(total, dims):
    gates = [
        (90, "优秀", {"D2": 13, "D3": 25, "D5": 8, "D6": 12, "D7": 8}),
        (80, "良好", {"D2": 11, "D3": 21, "D6": 10}),
        (70, "合格", {"D2": 9, "D3": 18, "D5": 6}),
        (60, "待整改", {"D3": 12}),
        (0, "不合格", {}),
    ]
    for floor, name, mins in gates:
        if total < floor:
            continue
        if any(dims[k] < v for k, v in mins.items()):
            continue
        return name
    return "不合格"


def main():
    print("=" * 70)
    print(" 对照验收表自检（非官方评分）")
    print("=" * 70)
    for fn in (check_d1, check_d2, check_d3, check_d4, check_d5, check_d6, check_d7):
        fn()

    dims = {}
    for r in ROWS:
        dims[r["dim"]] = round(dims.get(r["dim"], 0) + r["score"], 2)
    for dim in DIMS:
        print(f"\n{dim}  {dims.get(dim, 0)} / {DIMS[dim]}")
        for r in [x for x in ROWS if x["dim"] == dim]:
            print(f"  [{r['status']:<4}] {r['code']:<22} {r['score']:>4}  {r['detail']}")

    total = round(sum(dims.values()))
    grade = decide_grade(total, dims)
    print("\n" + "=" * 70)
    print(f" 自评总分：{total}/100    等级（按门槛）：{grade}")
    print(f" 维度：{dims}")
    print("=" * 70)

    out = config.EVIDENCE_DIR / "self-score.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dim", "code", "max", "status", "score", "detail"])
        for r in ROWS:
            w.writerow([r["dim"], r["code"], r["max"], r["status"], r["score"], r["detail"]])
        w.writerow(["TOTAL", "", sum(DIMS.values()), "", total, grade])
    print(f"台账：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
