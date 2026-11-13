# -*- coding: utf-8 -*-
"""
演示服务（FastAPI）：
  GET  /                     演示页
  GET  /mobile               移动端 APP 壳
  GET  /manifest.json        PWA manifest
  GET  /health               组件健康（含模型与后台任务）
  POST /ask                  问答主接口
  GET  /demo/cases           演示用例
  GET  /admin/kb/stats       知识库统计
  POST /admin/kb/sync        立即同步 inbox
  GET  /admin/kb/pending     审核队列
  POST /admin/kb/approve     审核通过并入库
  GET  /admin/regression     题库回归
  POST /admin/backup/run     立即备份
  GET  /admin/backup/status  备份状态
  GET  /admin/scheduler/status 后台任务状态
  GET  /admin/logs           最近问答日志
"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
import qa_service
import runtime
import storage
from backup.backup import last_status, run_backup
from kb import auto_add
from segment import build_dict

START_TS = time.time()


class AskBody(BaseModel):
    question: str = ""


class BackupBody(BaseModel):
    dry_run: bool | None = None


class ApproveBody(BaseModel):
    doc_id: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：建表 -> 首次自动灌语料 -> 重建词典 -> 预热模型 -> 起后台任务。"""
    storage.init_db()
    if storage.graph_stats()["nodes"] == 0:
        auto_add.sync_once()      # 首次启动自动把 data/inbox 的语料入库
    build_dict(force=True)
    qa_service.warmup()           # 模型预加载，避免首个请求承担加载耗时
    runtime.start()               # 目录监听 + 定时同步 + 定时备份
    yield
    runtime.stop()


app = FastAPI(title="医药知识图谱问答系统", version="1.0.0", lifespan=lifespan)

# 便于移动端 / PWA 跨源调试（本地演示场景）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _serve(path, media_type=None):
    """统一静态文件出口；越界路径直接 404。"""
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if media_type:
        return FileResponse(path, media_type=media_type)
    return FileResponse(path)


@app.get("/", response_class=HTMLResponse)
def index():
    page = config.BASE_DIR / "web" / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>web/index.html 缺失</h1>", status_code=500)
    return HTMLResponse(page.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.get("/mobile", response_class=HTMLResponse)
def mobile():
    page = config.BASE_DIR / "mobile" / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>mobile/index.html 缺失</h1>", status_code=500)
    return HTMLResponse(page.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.get("/manifest.json")
def manifest():
    return _serve(config.BASE_DIR / "web" / "manifest.json",
                  "application/manifest+json")


@app.get("/mobile/manifest.json")
def mobile_manifest():
    return _serve(config.BASE_DIR / "mobile" / "manifest.json",
                  "application/manifest+json")


@app.get("/icons/{name}")
def icons(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=404)
    return _serve(config.BASE_DIR / "web" / "icons" / name, "image/png")


@app.get("/health")
def health():
    g = storage.graph_stats()
    return {
        "status": "ok",
        "uptime_sec": round(time.time() - START_TS, 1),
        "components": {
            "sqlite": {"ok": True, "path": str(config.DB_PATH)},
            "graph": {"ok": g["nodes"] > 0, **g},
            "qa": {"ok": True, "threshold": config.CONF_THRESHOLD},
            "model": qa_service.model_info(),
            "scheduler": {"ok": True, **runtime.status()},
        },
        "questions": storage.qb_count(),
        "pending": storage.pending_count(),
    }


@app.post("/ask")
def ask(body: AskBody):
    if not body.question.strip():
        return JSONResponse({"error": "question 不能为空"}, status_code=400)
    return qa_service.ask(body.question)


@app.get("/demo/cases")
def demo_cases():
    return {
        "cases": [
            {"label": "正常·用药", "question": "风热感冒吃什么药", "expect": "ok"},
            {"label": "正常·症状", "question": "风热感冒有哪些症状", "expect": "ok"},
            {"label": "正常·检查", "question": "高血压需要做什么检查", "expect": "ok"},
            {"label": "正常·预防", "question": "怎么预防2型糖尿病", "expect": "ok"},
            # 急性胃炎语料刻意不含“检查”小节，用来演示“空结果不编造”
            {"label": "空结果", "question": "急性胃炎需要做什么检查", "expect": "empty"},
            {"label": "低置信度", "question": "那个东西能不能吃", "expect": "clarify"},
            {"label": "高风险", "question": "孕妇胸闷气短怎么办", "expect": "safety"},
            {"label": "待扩展", "question": "风热感冒和板蓝根一起吃会冲突吗", "expect": "pending"},
        ]
    }


@app.get("/admin/kb/stats")
def kb_stats():
    return auto_add.inbox_stats()


@app.post("/admin/kb/sync")
def kb_sync():
    return auto_add.sync_once()


@app.get("/admin/kb/pending")
def kb_pending():
    return {"total": storage.pending_count(), "items": storage.pending_all()}


@app.post("/admin/kb/approve")
def kb_approve(body: ApproveBody):
    if not body.doc_id:
        return JSONResponse({"ok": False, "reason": "doc_id 不能为空"}, status_code=400)
    return auto_add.approve(body.doc_id)


@app.get("/admin/regression")
def regression():
    return qa_service.regression()


@app.post("/admin/backup/run")
def backup_run(body: BackupBody | None = None):
    dry = config.BACKUP_DRY_RUN if (body is None or body.dry_run is None) else body.dry_run
    return run_backup(dry_run=dry)


@app.get("/admin/backup/status")
def backup_status():
    return last_status()


@app.get("/admin/scheduler/status")
def scheduler_status():
    return runtime.status()


@app.get("/admin/logs")
def logs(limit: int = 20):
    return {"logs": storage.recent_logs(limit)}


if __name__ == "__main__":
    import uvicorn

    print("=" * 56)
    print(" 医药知识图谱问答系统 已启动")
    print(f" 本机访问:   http://127.0.0.1:{config.PORT}")
    print(f" 移动端壳:   http://127.0.0.1:{config.PORT}/mobile")
    print(f" 局域网访问: http://<本机IP>:{config.PORT}")
    print(" 按 Ctrl+C 停止")
    print("=" * 56)
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
