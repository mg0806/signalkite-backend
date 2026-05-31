from datetime import datetime
import json

import redis
from rq import Queue
from sqlalchemy.orm import Session

from config import settings
from db import SessionLocal
from models import MarketScanJob
from services.market_scanner import scan_market_top_picks


def create_scan_job(db: Session, limit_per_category: int = 2) -> MarketScanJob:
    job = MarketScanJob(status="queued", limit_per_category=limit_per_category)
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        queue = Queue("market-scans", connection=redis.from_url(settings.redis_url))
        queue.enqueue(run_scan_job, job.id, job_timeout=600)
    except Exception:
        run_scan_job(job.id)
    db.refresh(job)
    return job


def run_scan_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(MarketScanJob).filter(MarketScanJob.id == job_id).one()
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        result = scan_market_top_picks(limit_per_category=job.limit_per_category)
        job.result_json = json.dumps(result)
        job.status = "succeeded"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.query(MarketScanJob).filter(MarketScanJob.id == job_id).one_or_none()
        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def serialize_scan_job(job: MarketScanJob, include_result: bool = True) -> dict:
    result = json.loads(job.result_json) if include_result and job.result_json else None
    return {
        "id": job.id,
        "status": job.status,
        "limit_per_category": job.limit_per_category,
        "result": result,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
