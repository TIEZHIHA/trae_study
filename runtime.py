# -*- coding: utf-8 -*-
"""
后台常驻（方案三层架构的第三层）：
  1. 定时同步：每 KB_SYNC_INTERVAL_MIN 分钟扫一次 inbox；
  2. 目录监听：watchdog 监听 inbox，新文件落盘 1.5 秒后触发同步；
  3. 定时备份：每天 BACKUP_CRON_HOUR 点执行一次（默认 dry run）。

所有后台任务都是 daemon 线程，服务退出即结束；异常只记录状态，不杀死线程。
"""
import threading
from datetime import datetime

import config
from backup.backup import run_backup
from kb import auto_add

_state = {
    "started_at": "",
    "watcher": False,
    "sync_last": "",
    "sync_count": 0,
    "backup_last": "",
    "backup_count": 0,
    "interval_min": config.KB_SYNC_INTERVAL_MIN,
    "backup_hour": config.BACKUP_CRON_HOUR,
    "dry_run": config.BACKUP_DRY_RUN,
}
_stop = threading.Event()
_timer_lock = threading.Lock()
_debounce = {"timer": None}


def _sync_once(reason):
    try:
        r = auto_add.sync_once()
        _state["sync_count"] += 1
        _state["sync_last"] = (f"{datetime.now():%Y-%m-%d %H:%M:%S} [{reason}] "
                               f"scanned={r['scanned']} added={r['added']} "
                               f"pending={r.get('pending', 0)} elapsed={r['elapsed_ms']}ms")
    except Exception as e:
        _state["sync_last"] = f"{datetime.now():%Y-%m-%d %H:%M:%S} [error] {type(e).__name__}: {e}"


def _sync_loop():
    interval = max(1, config.KB_SYNC_INTERVAL_MIN) * 60
    while not _stop.wait(interval):
        _sync_once("timer")


def _backup_loop():
    last_day = None
    while not _stop.wait(30):
        now = datetime.now()
        if now.hour == config.BACKUP_CRON_HOUR and last_day != now.date():
            last_day = now.date()
            try:
                r = run_backup(dry_run=config.BACKUP_DRY_RUN)
                _state["backup_count"] += 1
                _state["backup_last"] = (f"{datetime.now():%Y-%m-%d %H:%M:%S} "
                                         f"status={r['status']} package={r.get('package')}")
            except Exception as e:
                _state["backup_last"] = f"{datetime.now():%Y-%m-%d %H:%M:%S} [error] {e}"


def _schedule_sync():
    """目录监听去抖：1.5 秒内的多次文件事件只触发一次同步。"""
    with _timer_lock:
        if _debounce["timer"]:
            _debounce["timer"].cancel()
        t = threading.Timer(1.5, lambda: _sync_once("watch"))
        t.daemon = True
        _debounce["timer"] = t
        t.start()


def _start_watcher():
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        _state["watcher"] = False
        return None

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                _schedule_sync()

        def on_modified(self, event):
            if not event.is_directory:
                _schedule_sync()

        def on_moved(self, event):
            if not event.is_directory:
                _schedule_sync()

    observer = Observer()
    observer.schedule(_Handler(), str(config.INBOX_DIR), recursive=True)
    observer.daemon = True
    observer.start()
    _state["watcher"] = True
    return observer


_observer = None


def start():
    """启动三个后台任务；重复调用安全。"""
    global _observer
    if _state["started_at"]:
        return _state
    _state["started_at"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    _stop.clear()

    for target in (_sync_loop, _backup_loop):
        t = threading.Thread(target=target, daemon=True)
        t.start()

    _observer = _start_watcher()
    return _state


def stop():
    global _observer
    _stop.set()
    if _observer:
        try:
            _observer.stop()
        except Exception:
            pass
        _observer = None
    _state["watcher"] = False


def status():
    return dict(_state)
