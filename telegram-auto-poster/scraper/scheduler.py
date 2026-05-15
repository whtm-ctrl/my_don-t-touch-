"""
Scheduler module for managing post timing and rate limits.
Handles weekday/weekend schedules, hourly/daily limits, and intervals.
"""

from datetime import datetime, time, timezone, timedelta
from typing import Optional, Tuple
import structlog

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import SchedulerSettings, Post, PostedMessage

logger = structlog.get_logger(__name__)


class PostScheduler:
    """
    Scheduler for managing post timing and rate limits.
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._settings_cache: Optional[SchedulerSettings] = None

    async def load_settings(self) -> SchedulerSettings:
        """Load scheduler settings from database."""
        try:
            result = await self.db.execute(select(SchedulerSettings).limit(1))
            settings = result.scalar_one_or_none()
            
            if settings:
                self._settings_cache = settings
                return settings
            
            # Create default settings if none exist
            settings = SchedulerSettings()
            self.db.add(settings)
            await self.db.flush()
            self._settings_cache = settings
            return settings
            
        except Exception as e:
            logger.error("Failed to load scheduler settings", error=str(e))
            raise

    def is_within_schedule(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if current time is within posting schedule.
        
        Args:
            dt: DateTime to check (default: now)
        
        Returns:
            True if within schedule, False otherwise
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        
        if not self._settings_cache:
            return True  # No restrictions if no settings
        
        settings = self._settings_cache
        
        # Check if scheduler is active
        if not settings.is_active:
            return False
        
        # Determine if weekend
        is_weekend = dt.weekday() >= 5  # Saturday=5, Sunday=6
        
        # Get appropriate time range
        if is_weekend:
            start_time = settings.weekend_start_time
            end_time = settings.weekend_end_time
        else:
            start_time = settings.weekday_start_time
            end_time = settings.weekday_end_time
        
        current_time = dt.time()
        
        # Handle overnight schedules (e.g., 22:00 to 06:00)
        if start_time <= end_time:
            return start_time <= current_time <= end_time
        else:
            # Overnight: before end_time OR after start_time
            return current_time >= start_time or current_time <= end_time

    async def check_hourly_limit(self) -> Tuple[bool, int]:
        """
        Check if hourly post limit has been reached.
        
        Returns:
            (can_post, current_count)
        """
        if not self._settings_cache:
            await self.load_settings()
        
        settings = self._settings_cache
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        try:
            result = await self.db.execute(
                select(func.count(PostedMessage.id)).where(
                    PostedMessage.posted_at >= one_hour_ago
                )
            )
            count = result.scalar() or 0
            
            can_post = count < settings.max_posts_per_hour
            return can_post, count
            
        except Exception as e:
            logger.error("Failed to check hourly limit", error=str(e))
            return True, 0  # Allow on error

    async def check_daily_limit(self) -> Tuple[bool, int]:
        """
        Check if daily post limit has been reached.
        
        Returns:
            (can_post, current_count)
        """
        if not self._settings_cache:
            await self.load_settings()
        
        settings = self._settings_cache
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        try:
            result = await self.db.execute(
                select(func.count(PostedMessage.id)).where(
                    PostedMessage.posted_at >= today_start
                )
            )
            count = result.scalar() or 0
            
            can_post = count < settings.max_posts_per_day
            return can_post, count
            
        except Exception as e:
            logger.error("Failed to check daily limit", error=str(e))
            return True, 0  # Allow on error

    async def check_interval(self) -> Tuple[bool, float]:
        """
        Check if minimum interval since last post has passed.
        
        Returns:
            (can_post, seconds_since_last)
        """
        if not self._settings_cache:
            await self.load_settings()
        
        settings = self._settings_cache
        
        try:
            result = await self.db.execute(
                select(PostedMessage.posted_at)
                .order_by(PostedMessage.posted_at.desc())
                .limit(1)
            )
            last_post = result.scalar_one_or_none()
            
            if last_post is None:
                return True, float('inf')  # No previous posts
            
            seconds_since_last = (datetime.now(timezone.utc) - last_post).total_seconds()
            can_post = seconds_since_last >= settings.min_interval_seconds
            
            return can_post, seconds_since_last
            
        except Exception as e:
            logger.error("Failed to check interval", error=str(e))
            return True, float('inf')  # Allow on error

    async def can_post_now(self) -> Tuple[bool, str]:
        """
        Comprehensive check if a post can be made right now.
        
        Returns:
            (can_post, reason)
        """
        # Check schedule
        if not self.is_within_schedule():
            return False, "outside_schedule"
        
        # Check hourly limit
        can_post_hourly, hourly_count = await self.check_hourly_limit()
        if not can_post_hourly:
            return False, f"hourly_limit_reached ({hourly_count})"
        
        # Check daily limit
        can_post_daily, daily_count = await self.check_daily_limit()
        if not can_post_daily:
            return False, f"daily_limit_reached ({daily_count})"
        
        # Check interval
        can_post_interval, seconds_since = await self.check_interval()
        if not can_post_interval:
            wait_time = self._settings_cache.min_interval_seconds - seconds_since
            return False, f"interval_not_met (wait {wait_time:.0f}s)"
        
        return True, "ok"

    async def get_next_available_time(self) -> Optional[datetime]:
        """
        Calculate the next available time for posting.
        
        Returns:
            Next available datetime or None if unknown
        """
        now = datetime.now(timezone.utc)
        
        # Check schedule first
        if not self.is_within_schedule(now):
            if not self._settings_cache:
                await self.load_settings()
            
            settings = self._settings_cache
            is_weekend = now.weekday() >= 5
            
            if is_weekend:
                start_time = settings.weekend_start_time
            else:
                start_time = settings.weekday_start_time
            
            # Next day at start time
            next_day = now.date() + timedelta(days=1)
            return datetime.combine(next_day, start_time, tzinfo=timezone.utc)
        
        # Check interval
        can_post, seconds_since = await self.check_interval()
        if not can_post and self._settings_cache:
            wait_seconds = self._settings_cache.min_interval_seconds - seconds_since
            return now + timedelta(seconds=wait_seconds)
        
        # Can post now
        return now

    def get_wait_time_description(self) -> str:
        """Get human-readable description of current wait status."""
        if self.is_within_schedule():
            return "Within posting schedule"
        else:
            return "Outside posting hours"
