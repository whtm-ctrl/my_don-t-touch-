"""
n8n client for webhook integration.
Handles sending posts to n8n for AI processing and publishing.
Supports retries and Redis queue for reliability.
"""

import json
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import structlog
import httpx

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

logger = structlog.get_logger(__name__)


class N8NClient:
    """
    Client for interacting with n8n webhooks.
    Handles retries and queuing.
    """

    def __init__(self):
        self.webhook_url = str(settings.n8n_webhook_url) if settings.n8n_webhook_url else None
        self._redis_client = None
        self.queue_name = "n8n_pending_posts"

    async def get_redis_client(self):
        """Get or create Redis client."""
        if self._redis_client is None:
            import redis.asyncio as redis
            self._redis_client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis_client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True
    )
    async def send_webhook(
        self,
        post_data: Dict[str, Any],
        timeout: float = 30.0
    ) -> bool:
        """
        Send post data to n8n webhook with retries.
        
        Args:
            post_data: Dictionary containing post information
            timeout: Request timeout in seconds
        
        Returns:
            True if successful, False otherwise
        """
        if not self.webhook_url:
            logger.warning("n8n webhook URL not configured")
            return False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self.webhook_url,
                    json=post_data,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201, 202]:
                    logger.info(
                        "Webhook sent successfully",
                        status=response.status_code,
                        post_id=post_data.get("id")
                    )
                    return True
                else:
                    logger.warning(
                        "Webhook returned error status",
                        status=response.status_code,
                        body=response.text[:500]
                    )
                    return False
                    
        except httpx.TimeoutException as e:
            logger.error("Webhook request timed out", error=str(e))
            raise
        except httpx.NetworkError as e:
            logger.error("Webhook network error", error=str(e))
            raise
        except Exception as e:
            logger.error("Webhook request failed", error=str(e))
            return False

    async def queue_post(self, post_data: Dict[str, Any]) -> bool:
        """
        Add post to Redis queue for later processing.
        
        Args:
            post_data: Dictionary containing post information
        
        Returns:
            True if queued successfully
        """
        try:
            redis_client = await self.get_redis_client()
            
            # Serialize post data with timestamp
            queued_data = {
                "data": post_data,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": 0
            }
            
            await redis_client.lpush(
                self.queue_name,
                json.dumps(queued_data)
            )
            
            logger.info(
                "Post queued for n8n",
                queue_length=await redis_client.llen(self.queue_name),
                post_id=post_data.get("id")
            )
            return True
            
        except Exception as e:
            logger.error("Failed to queue post", error=str(e))
            return False

    async def process_queue(self, batch_size: int = 10) -> int:
        """
        Process queued posts from Redis.
        
        Args:
            batch_size: Number of posts to process in one batch
        
        Returns:
            Number of successfully processed posts
        """
        try:
            redis_client = await self.get_redis_client()
            processed_count = 0
            
            for _ in range(batch_size):
                # Get item from queue (right side - oldest first)
                item = await redis_client.rpop(self.queue_name)
                
                if not item:
                    break
                
                try:
                    queued_data = json.loads(item)
                    post_data = queued_data["data"]
                    
                    success = await self.send_webhook(post_data)
                    
                    if success:
                        processed_count += 1
                    else:
                        # Re-queue with incremented retry count
                        retry_count = queued_data.get("retry_count", 0) + 1
                        if retry_count < 5:
                            queued_data["retry_count"] = retry_count
                            await redis_client.lpush(
                                self.queue_name,
                                json.dumps(queued_data)
                            )
                            logger.warning(
                                "Post re-queued after failure",
                                retry_count=retry_count,
                                post_id=post_data.get("id")
                            )
                        else:
                            logger.error(
                                "Post dropped after max retries",
                                post_id=post_data.get("id")
                            )
                            
                except json.JSONDecodeError as e:
                    logger.error("Invalid queued data", error=str(e))
                    continue
                    
            if processed_count > 0:
                logger.info(
                    "Queue processing completed",
                    processed=processed_count,
                    remaining=await redis_client.llen(self.queue_name)
                )
            
            return processed_count
            
        except Exception as e:
            logger.error("Queue processing failed", error=str(e))
            return 0

    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the pending queue.
        
        Returns:
            Dictionary with queue statistics
        """
        try:
            redis_client = await self.get_redis_client()
            queue_length = await redis_client.llen(self.queue_name)
            
            # Get approximate age of oldest item
            oldest_item = await redis_client.lindex(self.queue_name, -1)
            oldest_age = None
            
            if oldest_item:
                try:
                    data = json.loads(oldest_item)
                    queued_at = datetime.fromisoformat(data["queued_at"].replace('Z', '+00:00'))
                    oldest_age = (datetime.now(timezone.utc) - queued_at).total_seconds()
                except Exception:
                    pass
            
            return {
                "queue_length": queue_length,
                "oldest_item_age_seconds": oldest_age,
                "webhook_configured": bool(self.webhook_url)
            }
            
        except Exception as e:
            logger.error("Failed to get queue stats", error=str(e))
            return {
                "queue_length": 0,
                "oldest_item_age_seconds": None,
                "webhook_configured": False,
                "error": str(e)
            }

    def prepare_post_payload(
        self,
        post_id: str,
        text: Optional[str],
        media_path: Optional[str],
        media_type: Optional[str],
        source_channel: str,
        quality_score: float
    ) -> Dict[str, Any]:
        """
        Prepare standardized payload for n8n webhook.
        
        Returns:
            Dictionary ready to be sent to webhook
        """
        return {
            "id": post_id,
            "text": text,
            "media": {
                "path": media_path,
                "type": media_type
            } if media_path and media_type else None,
            "source": {
                "channel": source_channel
            },
            "quality_score": quality_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "service": "telegram-auto-poster",
                "version": "1.0.0"
            }
        }
