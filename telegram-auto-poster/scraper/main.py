"""
Main entry point for the Telegram Scraper service.
Handles MTProto scraping, filtering, and posting workflow.
"""

import asyncio
import signal
from datetime import datetime, timezone
from typing import Optional
import structlog

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.types import Message, Channel, Chat, User

from config import settings
from database import get_db, async_session_maker, init_db, close_db
from models import SourceChannel, Post, TargetChannel, PostedMessage, ErrorLog
from filters import ContentFilter
from media_handler import MediaHandler
from scheduler import PostScheduler
from n8n_client import N8NClient

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class TelegramScraper:
    """
    Main scraper class handling all Telegram operations.
    """

    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.media_handler = MediaHandler()
        self.n8n_client = N8NClient()
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize the Telegram client."""
        if not settings.validate_telegram_credentials():
            logger.error("Missing Telegram credentials")
            raise ValueError("TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE are required")

        # Initialize database
        await init_db()

        # Create Telethon client
        session_path = f"{settings.session_path}/telegram_scraper"
        self.client = TelegramClient(
            session_path,
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            system_version="4.16.30-vxCUSTOM",
            app_version="2.10.3-custom",
            device_model="Custom Scraper"
        )

        logger.info("Telegram client initialized")

    async def start(self):
        """Start the Telegram client and begin scraping."""
        await self.initialize()

        # Connect and authorize
        await self.client.start(phone=settings.telegram_phone)
        logger.info("Telegram client started", user=(await self.client.get_me()).username)

        self._running = True
        
        # Start main scraping loop
        asyncio.create_task(self.scraping_loop())
        
        # Start queue processor
        asyncio.create_task(self.queue_processor_loop())
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self):
        """Stop the scraper gracefully."""
        logger.info("Stopping scraper...")
        self._running = False
        self._shutdown_event.set()
        
        if self.client:
            await self.client.disconnect()
        
        await close_db()
        logger.info("Scraper stopped")

    async def scraping_loop(self, interval: int = 60):
        """
        Main scraping loop that periodically checks source channels.
        
        Args:
            interval: Seconds between scraping cycles
        """
        logger.info("Starting scraping loop", interval=interval)
        
        while self._running:
            try:
                await self.scrape_all_channels()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scraping loop error", error=str(e))
                await self.log_error("scraper", "scraping_loop", str(e))
                await asyncio.sleep(interval)

    async def queue_processor_loop(self, interval: int = 30):
        """
        Process queued posts for n8n.
        
        Args:
            interval: Seconds between queue processing
        """
        logger.info("Starting queue processor loop", interval=interval)
        
        while self._running:
            try:
                processed = await self.n8n_client.process_queue(batch_size=5)
                if processed > 0:
                    logger.info("Processed queued posts", count=processed)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Queue processor error", error=str(e))
                await asyncio.sleep(interval)

    async def scrape_all_channels(self):
        """Scrape all active source channels."""
        async with async_session_maker() as db:
            # Get active source channels
            from sqlalchemy import select
            result = await db.execute(
                select(SourceChannel).where(SourceChannel.is_active == True)
            )
            channels = result.scalars().all()

            if not channels:
                logger.debug("No active source channels configured")
                return

            logger.info("Scraping channels", count=len(channels))

            for channel in channels:
                try:
                    await self.scrape_channel(db, channel)
                except Exception as e:
                    logger.error(
                        "Failed to scrape channel",
                        channel=channel.username,
                        error=str(e)
                    )
                    await self.log_error("scraper", "scrape_channel", str(e), {"channel": channel.username})

    async def scrape_channel(self, db, channel: SourceChannel):
        """
        Scrape new messages from a specific channel.
        
        Args:
            db: Database session
            channel: Source channel model
        """
        try:
            # Get entity
            entity = await self.client.get_entity(channel.username)
            
            # Get last scraped message ID
            last_message_id = channel.messages_count
            
            # Fetch recent messages
            messages = await self.client.get_messages(
                entity,
                limit=50,
                offset_id=last_message_id + 1 if last_message_id > 0 else 0
            )

            if not messages:
                logger.debug("No new messages", channel=channel.username)
                return

            # Initialize filter
            content_filter = ContentFilter(db)
            await content_filter.load_filters()

            # Initialize scheduler
            scheduler = PostScheduler(db)
            await scheduler.load_settings()

            processed_count = 0
            for message in messages:
                if not isinstance(message, Message):
                    continue
                    
                success = await self.process_message(
                    db, channel, message, content_filter, scheduler
                )
                if success:
                    processed_count += 1

            # Update channel stats
            if messages:
                channel.messages_count = max(channel.messages_count, messages[0].id)
                channel.last_scraped_at = datetime.now(timezone.utc)

            logger.info(
                "Channel scraped",
                channel=channel.username,
                messages=len(messages),
                processed=processed_count
            )

        except FloodWaitError as e:
            logger.warning(
                "Flood wait detected",
                channel=channel.username,
                wait_seconds=e.seconds
            )
            await asyncio.sleep(e.seconds)
            raise
        except Exception as e:
            logger.error(
                "Channel scrape failed",
                channel=channel.username,
                error=str(e)
            )
            raise

    async def process_message(
        self,
        db,
        channel: SourceChannel,
        message: Message,
        content_filter: ContentFilter,
        scheduler: PostScheduler
    ) -> bool:
        """
        Process a single message.
        
        Returns:
            True if message was successfully processed
        """
        # Extract text
        text = message.text or message.message or ""
        
        # Check if message has media
        has_media = message.media is not None
        media_type = None
        media_path = None

        # Download media if present
        if has_media:
            try:
                media_path_obj = await self.download_media(message)
                if media_path_obj:
                    media_path = str(media_path_obj)
                    media_type = self.media_handler.get_media_type(media_path_obj)
                    
                    # Process image (watermark + compress)
                    if media_type == 'photo':
                        processed_path = self.media_handler.process_media(
                            media_path_obj,
                            watermark_text="@YourChannel"
                        )
                        if processed_path:
                            media_path = str(processed_path)
            except Exception as e:
                logger.warning("Media download failed", error=str(e))

        # Skip empty messages without media
        if not text and not media_path:
            return False

        # Validate content
        is_valid, reason, quality_score = await content_filter.validate_post(
            text=text if text else "",
            has_media=bool(media_path)
        )

        if not is_valid:
            logger.debug(
                "Post filtered out",
                channel=channel.username,
                message_id=message.id,
                reason=reason
            )
            await self.save_post(db, channel, message, text, media_type, media_path, "skipped", reason, 0.0)
            return False

        # Check scheduler
        can_post, schedule_reason = await scheduler.can_post_now()
        
        # Save post to database
        status = "pending" if can_post else "queued"
        post = await self.save_post(
            db, channel, message, text, media_type, media_path,
            status, schedule_reason if not can_post else "passed", quality_score
        )

        if can_post:
            # Send to n8n
            payload = self.n8n_client.prepare_post_payload(
                post_id=str(post.id),
                text=text,
                media_path=media_path,
                media_type=media_type,
                source_channel=channel.username,
                quality_score=quality_score
            )

            success = await self.n8n_client.send_webhook(payload)
            
            if success:
                post.status = "processed"
                logger.info(
                    "Post sent to n8n",
                    post_id=post.id,
                    channel=channel.username
                )
            else:
                # Queue for later
                await self.n8n_client.queue_post(payload)
                post.status = "queued"
        else:
            # Queue for later when schedule allows
            payload = self.n8n_client.prepare_post_payload(
                post_id=str(post.id),
                text=text,
                media_path=media_path,
                media_type=media_type,
                source_channel=channel.username,
                quality_score=quality_score
            )
            await self.n8n_client.queue_post(payload)
            logger.info(
                "Post queued (schedule restriction)",
                post_id=post.id,
                reason=schedule_reason
            )

        return True

    async def download_media(self, message: Message) -> Optional[str]:
        """Download media from message."""
        if not message.media:
            return None

        try:
            file_path = await self.client.download_media(
                message.media,
                file=settings.media_path + "/"
            )
            return file_path
        except Exception as e:
            logger.error("Media download failed", error=str(e))
            return None

    async def save_post(
        self,
        db,
        channel: SourceChannel,
        message: Message,
        text: str,
        media_type: Optional[str],
        media_path: Optional[str],
        status: str,
        error_message: Optional[str],
        quality_score: float
    ) -> Post:
        """Save post to database."""
        from sqlalchemy import select
        
        # Check if already exists
        existing = await db.execute(
            select(Post).where(
                Post.source_channel_id == channel.id,
                Post.message_id == message.id
            )
        )
        
        if existing.scalar_one_or_none():
            logger.debug("Post already exists", message_id=message.id)
            return None

        post = Post(
            source_channel_id=channel.id,
            message_id=message.id,
            text=text,
            media_type=media_type,
            media_path=media_path,
            views_count=message.views or 0 if hasattr(message, 'views') else 0,
            status=status,
            error_message=error_message,
            quality_score=quality_score
        )

        db.add(post)
        await db.flush()
        
        return post

    async def log_error(
        self,
        service: str,
        error_type: str,
        message: str,
        context: Optional[dict] = None,
        stack_trace: Optional[str] = None
    ):
        """Log error to database."""
        try:
            async with async_session_maker() as db:
                error_log = ErrorLog(
                    service_name=service,
                    error_type=error_type,
                    error_message=message,
                    context=context or {},
                    stack_trace=stack_trace
                )
                db.add(error_log)
        except Exception as e:
            logger.error("Failed to log error to database", error=str(e))


async def main():
    """Main entry point."""
    scraper = TelegramScraper()
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(scraper.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await scraper.start()
    except Exception as e:
        logger.error("Fatal error", error=str(e))
        await scraper.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
