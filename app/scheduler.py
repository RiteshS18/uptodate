"""
Background scheduler service for automated source refresh (RSS, websites, YouTube channels).

Uses APScheduler to periodically poll all followed sources, extract new articles and videos,
run noise filtering, summarize items, perform cross-source deduplication, and update the newspaper database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_is_refreshing: bool = False
_last_refresh_time: Optional[datetime] = None
_last_refresh_stats: dict = {"new_items": 0, "sources_checked": 0, "errors": 0}


def get_scheduler_status() -> dict:
    """Return status information about the background refresh scheduler."""
    return {
        "running": bool(_scheduler and _scheduler.running),
        "is_refreshing": _is_refreshing,
        "last_refresh_at": _last_refresh_time.isoformat() if _last_refresh_time else None,
        "last_stats": _last_refresh_stats,
    }


async def refresh_all_sources(limit_per_source: int = 4) -> dict:
    """
    Poll all followed sources, fetch genuinely new items, extract & summarize them,
    and save them to the database.
    """
    global _is_refreshing, _last_refresh_time, _last_refresh_stats
    if _is_refreshing:
        logger.info("Source refresh is already running — skipping concurrent trigger.")
        return {"status": "in_progress", "message": "Refresh already running"}

    _is_refreshing = True
    _last_refresh_time = datetime.now(timezone.utc)
    new_items_count = 0
    errors_count = 0

    try:
        from app.database import get_all_sources, mark_seen, save_processed_item
        from app.fetcher import fetch_new_items
        from app.main import _scrape_and_process_article

        sources = await get_all_sources()
        logger.info("Starting refresh cycle for %d followed sources...", len(sources))

        for src in sources:
            try:
                items = await fetch_new_items(src)
                new_urls = [it["url"] for it in items if it.get("url")][:limit_per_source]
                
                for url in new_urls:
                    try:
                        res = await _scrape_and_process_article(url)
                        if res:
                            item_dict = res.model_dump()
                            item_dict["source_id"] = src["id"]
                            await save_processed_item(item_dict)
                            new_items_count += 1
                    except Exception as exc:
                        logger.warning("Failed processing refreshed item %s: %s", url, exc)
                        errors_count += 1
            except Exception as src_exc:
                logger.warning("Failed polling source %s: %s", src.get("url"), src_exc)
                errors_count += 1

        _last_refresh_stats = {
            "new_items": new_items_count,
            "sources_checked": len(sources),
            "errors": errors_count,
        }
        logger.info("Refresh cycle completed: %d new items from %d sources.", new_items_count, len(sources))
        return {
            "status": "success",
            "new_items_count": new_items_count,
            "sources_checked": len(sources),
            "errors_count": errors_count,
            "refreshed_at": _last_refresh_time.isoformat(),
        }

    finally:
        _is_refreshing = False


def start_scheduler(interval_minutes: int = 30) -> None:
    """Start the background scheduler task."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            refresh_all_sources,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="backstory_source_refresh",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        _scheduler.start()
        logger.info("Background source refresh scheduler started (interval: %d mins).", interval_minutes)


def shutdown_scheduler() -> None:
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Background source refresh scheduler stopped.")
        _scheduler = None
