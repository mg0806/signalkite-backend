from apscheduler.schedulers.background import BackgroundScheduler

from db import SessionLocal
from services.kite_sync import sync_all_users


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    def sync_job() -> None:
        db = SessionLocal()
        try:
            sync_all_users(db)
        finally:
            db.close()

    scheduler.add_job(sync_job, "interval", minutes=5, id="holdings-sync", replace_existing=True)
    scheduler.start()
    return scheduler
