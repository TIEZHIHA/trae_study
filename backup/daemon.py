# -*- coding: utf-8 -*-
"""容器内备份守护：按 BACKUP_CRON_HOUR 每天执行一次备份。"""
import time
from datetime import datetime

import config
from backup.backup import run_backup


def main():
    print(f"备份守护启动，每天 {config.BACKUP_CRON_HOUR}:00 执行，"
          f"DRY_RUN={config.BACKUP_DRY_RUN}", flush=True)
    last_day = None
    while True:
        now = datetime.now()
        if now.hour == config.BACKUP_CRON_HOUR and last_day != now.date():
            last_day = now.date()
            result = run_backup(dry_run=config.BACKUP_DRY_RUN)
            print(f"{now:%Y-%m-%d %H:%M:%S} {result}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
