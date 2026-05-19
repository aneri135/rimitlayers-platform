# backend/app/core/scheduler.py
#
# PURPOSE: Defines WHEN jobs run — the timing manager
#
# APScheduler runs jobs in a background thread.
# Your main FastAPI app runs in the foreground serving the dashboard.
# The scheduler runs quietly in the background polling Gmail.
# Two things happening at once — that's concurrency.
#
# WHY APSCHEDULER OVER CRON?
# Cron: a separate OS-level service, configured in crontab files,
#       runs processes independently. Harder to manage in Docker.
# APScheduler: runs INSIDE your Python app. Same process,
#       same logs, same config. Starts when app starts,
#       stops when app stops. Much simpler for our use case.
#
# JOB TYPES IN APSCHEDULER:
# IntervalTrigger: run every N minutes (what we use for polling)
# CronTrigger:     run at specific times e.g. "every day at 9am"
# DateTrigger:     run once at a specific datetime
#
# We use IntervalTrigger for Gmail polling (every 5 min)
# and CronTrigger for the daily summary (once per day at 8am).
import sys
import os
import logging
from datetime import datetime

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED
)

from app.core.config import settings
from app.core.polling import run_poll_cycle, get_daily_stats
from app.notifications.notifier import notifier

logger = logging.getLogger(__name__)


class RiMitScheduler:
    """
    Manages all scheduled background jobs.

    WHY A CLASS?
    The scheduler needs to be started and stopped cleanly.
    A class lets us hold the scheduler instance and call
    start()/stop() on it. Also makes it easy to add new
    jobs later without restructuring the code.
    """

    def __init__(self):
        # BackgroundScheduler runs jobs in daemon threads
        # Daemon threads automatically stop when the main
        # program exits — no zombie processes
        self.scheduler = BackgroundScheduler(
            job_defaults={
                # If a job takes too long and the next run is due,
                # skip the missed run rather than running twice
                "coalesce":     True,
                # Maximum number of simultaneously running instances
                # of the same job — we only want 1 at a time
                "max_instances": 1,
                # How many seconds late a job can start before
                # it's considered "missed" and skipped
                "misfire_grace_time": 60,
            }
        )

        # Register event listeners for monitoring
        self.scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )
        self.scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )
        self.scheduler.add_listener(
            self._on_job_missed,
            EVENT_JOB_MISSED
        )

        # Track stats for /metrics endpoint
        self.stats = {
            "total_runs":     0,
            "successful_runs": 0,
            "failed_runs":    0,
            "missed_runs":    0,
            "last_run":       None,
            "next_run":       None,
        }

        logger.info("Scheduler initialised")

    def start(self):
        """
        Starts all scheduled jobs.
        Called once when the application starts.

        JOB REGISTRATION:
        Each job has:
        - func: the function to call
        - trigger: when to call it
        - id: unique name (used to reference/pause/remove job)
        - name: human-readable description
        """
        # Job 1: Gmail polling — the main job
        # Runs every POLL_INTERVAL_MINUTES (5 by default from .env)
        self.scheduler.add_job(
            func=    run_poll_cycle,
            trigger= IntervalTrigger(
                minutes=settings.POLL_INTERVAL_MINUTES
            ),
            id=      "gmail_poll",
            name=    "Gmail inbox polling",
            # Run first poll immediately when app starts
            # Not waiting 5 minutes for the first check
            next_run_time=datetime.now()
        )
        logger.info(
            f"Gmail polling job registered — "
            f"interval: {settings.POLL_INTERVAL_MINUTES} minutes"
        )

        # Job 2: Daily summary — runs every morning at 8am
        # Sends a Telegram summary of yesterday's activity
        self.scheduler.add_job(
            func=    self._send_daily_summary,
            trigger= CronTrigger(
                hour=8,
                minute=0,
                # timezone="America/Chicago"
                # Uncomment and set your timezone
                # Houston is America/Chicago (CST/CDT)
            ),
            id=      "daily_summary",
            name=    "Daily activity summary",
        )
        logger.info("Daily summary job registered — runs at 8:00 AM")

        # Start the scheduler background thread
        self.scheduler.start()
        logger.info(
            "Scheduler started — "
            f"{len(self.scheduler.get_jobs())} jobs running"
        )

        # Update next_run in stats
        self._update_next_run()

    def stop(self):
        """
        Cleanly stops the scheduler.
        Called when the application shuts down.

        wait=True means: finish any currently running job
        before stopping. Don't cut off mid-execution.
        """
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped cleanly")

    def get_status(self) -> dict:
        """
        Returns current scheduler status.
        Used by the /api/scheduler/status endpoint.
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id":       job.id,
                "name":     job.name,
                "next_run": (
                    job.next_run_time.isoformat()
                    if job.next_run_time
                    else None
                ),
            })

        return {
            "running":  self.scheduler.running,
            "jobs":     jobs,
            "stats":    self.stats,
            "daily":    get_daily_stats(),
        }

    def trigger_manual_poll(self):
        """
        Triggers an immediate poll outside the normal schedule.
        Used by the dashboard "Poll now" button.

        WHY ALLOW MANUAL TRIGGER?
        Useful when you know you just got an order and
        don't want to wait for the next scheduled run.
        Also great for testing — you can trigger from
        the dashboard and watch the result immediately.
        """
        logger.info("Manual poll triggered from dashboard")
        try:
            result = run_poll_cycle()
            logger.info(f"Manual poll complete: {result}")
            return result
        except Exception as e:
            logger.error(f"Manual poll failed: {e}")
            return {"error": str(e)}

    def _send_daily_summary(self):
        """
        Sends a daily summary message at 8am.
        Only sends if there was activity — no noise on quiet days.
        """
        stats = get_daily_stats()
        logger.info(f"Sending daily summary: {stats}")
        notifier.polling_summary(
            orders_found=   stats.get("orders_found", 0),
            messages_found= stats.get("messages_found", 0),
            errors=         stats.get("errors", 0),
        )

    def _on_job_executed(self, event):
        """
        Called automatically by APScheduler after every
        successful job execution.

        EVENT LISTENERS:
        APScheduler fires events for every job lifecycle moment.
        We listen for EXECUTED, ERROR, and MISSED to:
        1. Update our stats counters
        2. Log appropriately
        3. Track timing for monitoring
        """
        self.stats["total_runs"]      += 1
        self.stats["successful_runs"] += 1
        self.stats["last_run"] = datetime.now().isoformat()
        self._update_next_run()

        logger.debug(
            f"Job '{event.job_id}' executed successfully"
        )

    def _on_job_error(self, event):
        """
        Called when a job raises an unhandled exception.
        Note: run_poll_cycle() catches its own errors internally,
        so this only fires for truly unexpected failures.
        """
        self.stats["total_runs"]   += 1
        self.stats["failed_runs"]  += 1
        self.stats["last_run"] = datetime.now().isoformat()

        logger.error(
            f"Job '{event.job_id}' raised an exception: "
            f"{event.exception}"
        )

    def _on_job_missed(self, event):
        """
        Called when a job couldn't run because the system
        was busy or overloaded (missed its window).
        With coalesce=True, missed runs are skipped not queued.
        """
        self.stats["missed_runs"] += 1
        logger.warning(
            f"Job '{event.job_id}' missed its scheduled run time. "
            f"Total missed: {self.stats['missed_runs']}"
        )

    def _update_next_run(self):
        """Updates the next_run stat from the scheduler."""
        try:
            job = self.scheduler.get_job("gmail_poll")
            if job and job.next_run_time:
                self.stats["next_run"] = (
                    job.next_run_time.isoformat()
                )
        except Exception:
            pass


# Single shared instance — created once, used everywhere
# The FastAPI app imports this and calls scheduler.start()
# on startup and scheduler.stop() on shutdown
scheduler = RiMitScheduler()