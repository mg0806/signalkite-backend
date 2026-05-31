import time

from config import settings
from db import SessionLocal
from services.kite_sync import sync_all_users


def run_once() -> None:
    db = SessionLocal()
    try:
        sync_all_users(db)
    finally:
        db.close()


def main() -> None:
    while True:
        run_once()
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
