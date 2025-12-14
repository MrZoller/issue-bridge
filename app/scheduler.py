"""Background scheduler for periodic sync"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.models import ProjectPair
from app.models.base import SessionLocal
from app.services.sync_service import SyncService

logger = logging.getLogger(__name__)


class SyncScheduler:
    """Scheduler for periodic issue synchronization"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        # Best-effort in-memory index of jobs we created.
        # APScheduler itself is the source of truth (see get_job()).
        self.jobs = {}

    def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info("Sync scheduler started")

        # Schedule all enabled project pairs
        self.schedule_all_pairs()

    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Sync scheduler stopped")

    def schedule_all_pairs(self):
        """Schedule sync jobs for all enabled project pairs"""
        db = SessionLocal()
        try:
            enabled_pairs = db.query(ProjectPair).filter(ProjectPair.sync_enabled == True).all()
            enabled_ids = {p.id for p in enabled_pairs}

            # If this is ever re-run, reconcile existing jobs too.
            for job_id in list(self.jobs.keys()):
                if not job_id.startswith("sync_pair_"):
                    continue
                try:
                    pair_id = int(job_id.split("sync_pair_", 1)[1])
                except Exception:
                    continue
                if pair_id not in enabled_ids:
                    self.unschedule_pair(pair_id)

            for pair in enabled_pairs:
                self.schedule_pair(pair.id, pair.sync_interval_minutes)
        finally:
            db.close()

    def schedule_pair(self, pair_id: int, interval_minutes: int):
        """Schedule sync job for a specific project pair"""
        job_id = f"sync_pair_{pair_id}"

        # Remove existing job if it exists (don't rely solely on self.jobs)
        existing = self.scheduler.get_job(job_id)
        if existing is not None:
            self.scheduler.remove_job(job_id)

        # Add new job
        self.scheduler.add_job(
            func=self._sync_pair_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=job_id,
            args=[pair_id],
            replace_existing=True,
        )
        self.jobs[job_id] = True
        logger.info(f"Scheduled sync for pair {pair_id} every {interval_minutes} minutes")

    def unschedule_pair(self, pair_id: int):
        """Remove sync job for a project pair"""
        job_id = f"sync_pair_{pair_id}"
        try:
            existing = self.scheduler.get_job(job_id)
            if existing is not None:
                self.scheduler.remove_job(job_id)
            self.jobs.pop(job_id, None)
            logger.info(f"Unscheduled sync for pair {pair_id}")
        except Exception as e:
            logger.error(f"Failed to unschedule pair {pair_id}: {e}")

    def _sync_pair_job(self, pair_id: int):
        """Job function to sync a project pair"""
        db = SessionLocal()
        try:
            logger.info(f"Running scheduled sync for pair {pair_id}")
            sync_service = SyncService(db)
            result = sync_service.sync_project_pair(pair_id)
            logger.info(f"Scheduled sync completed for pair {pair_id}: {result}")
        except Exception as e:
            logger.error(f"Scheduled sync failed for pair {pair_id}: {e}")
        finally:
            db.close()


# Global scheduler instance
scheduler = SyncScheduler()
