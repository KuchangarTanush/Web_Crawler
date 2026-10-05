"""
Scheduler: the periodic tick that decides what to crawl next.

"The scheduler checks which sources are due for crawling and creates the
required tasks" (design doc). Runs as a Celery beat task on a fixed
interval (SCHEDULER_TICK_SECONDS, default 30s). For each enabled source:
  - skip if a job for it is already in progress
  - skip if it isn't due yet
  - acquire a Redis lock to prevent duplicate jobs
  - enqueue a crawl job on the queue matching its priority
"""

import logging

from engine.celery_app import app
from engine.sources import load_sources
from engine.state import CrawlState
from engine.tasks import crawl_source


logger = logging.getLogger(__name__)

state = CrawlState()


@app.task
def check_and_schedule():
    scheduled = []

    for source in load_sources():

        # Skip disabled sources
        if not source.get("enabled", True):
            continue

        name = source["name"]

        # Skip if this source is already being crawled
        if state.is_in_progress(name):
            logger.debug(
                "Skipping '%s': already in progress",
                name
            )
            continue

        # Skip if the source is not due yet
        if not state.is_due(
            name,
            source["interval_minutes"]
        ):
            continue

        # Atomically claim the source before putting the job
        # into the Celery queue. This prevents duplicate jobs
        # if the scheduler runs again before the worker starts.
        if not state.acquire_lock(name):
            logger.debug(
                "Skipping '%s': already claimed",
                name
            )
            continue

        # Put the crawl into the queue corresponding to
        # the source priority.
        crawl_source.apply_async(
            args=[source],
            queue=source["priority"],
        )

        scheduled.append(name)

        logger.info(
            "Scheduled crawl for '%s' on queue '%s'",
            name,
            source["priority"],
        )

    return {
        "scheduled": scheduled
    }