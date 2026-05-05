from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from tools.content_tracker.services.scanner import (
    trigger_scheduled_assets_scan,
    trigger_scheduled_content_scan,
)

BRANDS = [
    'balterley', 'nuie', 'bc_designs', 'hudson_reed', 'bc_sanitan',
    'bayswater', 'wickes', 'arley', 'arley_pro', 'synergy',
]

_scheduler = None


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone='Europe/London')

    for i, brand in enumerate(BRANDS):
        # Asset scans: 00:00, 00:10, 00:20 … (10 min apart)
        a_hour   = (i * 10) // 60
        a_minute = (i * 10) % 60
        _scheduler.add_job(
            func=trigger_scheduled_assets_scan,
            args=[brand],
            trigger=CronTrigger(hour=a_hour, minute=a_minute),
            id=f'assets_{brand}',
            name=f'Asset scan: {brand}',
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Content scans: 02:00, 02:10, 02:20 … (after asset scans finish)
        c_base   = 120 + i * 10   # minutes from midnight
        c_hour   = c_base // 60
        c_minute = c_base % 60
        _scheduler.add_job(
            func=trigger_scheduled_content_scan,
            args=[brand],
            trigger=CronTrigger(hour=c_hour, minute=c_minute),
            id=f'content_{brand}',
            name=f'Content scan: {brand}',
            replace_existing=True,
            misfire_grace_time=3600,
        )

    _scheduler.start()
    return _scheduler


def get_job_info():
    if not _scheduler:
        return []
    return [
        {
            'id':       job.id,
            'name':     job.name,
            'next_run': job.next_run_time.strftime('%H:%M') if job.next_run_time else None,
        }
        for job in _scheduler.get_jobs()
    ]
