"""
Configuration settings for the Telegram Scraper.
Uses Pydantic Settings for environment variable management.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, HttpUrl
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = Field(
        default="postgresql://telegram_user:telegram_pass@postgres:5432/telegram_db",
        description="PostgreSQL connection URL"
    )

    # Redis
    redis_url: str = Field(
        default="redis://redis:6379",
        description="Redis connection URL"
    )

    # Telegram API
    telegram_api_id: int = Field(default=0, description="Telegram API ID")
    telegram_api_hash: str = Field(default="", description="Telegram API Hash")
    telegram_phone: str = Field(default="", description="Telegram phone number")
    telegram_session_string: Optional[str] = Field(
        default=None,
        description="Telegram session string (optional, will be created if not exists)"
    )

    # Bot Configuration
    bot_token: str = Field(default="", description="Telegram Bot Token")
    admin_chat_id: Optional[int] = Field(default=None, description="Admin chat ID for notifications")
    target_channel_id: Optional[str] = Field(default=None, description="Target channel ID for posting")

    # n8n Webhook
    n8n_webhook_url: Optional[HttpUrl] = Field(
        default=None,
        description="n8n webhook URL for AI processing and posting"
    )

    # Application
    log_level: str = Field(default="INFO", description="Logging level")
    session_path: str = Field(default="/app/sessions", description="Path to store Telethon sessions")
    media_path: str = Field(default="/app/media", description="Path to store downloaded media")

    # Scheduler defaults
    max_posts_per_hour: int = Field(default=5, description="Maximum posts per hour")
    max_posts_per_day: int = Field(default=50, description="Maximum posts per day")
    min_interval_seconds: int = Field(default=300, description="Minimum interval between posts in seconds")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def validate_telegram_credentials(self) -> bool:
        """Validate that required Telegram credentials are present."""
        return bool(
            self.telegram_api_id > 0 and
            self.telegram_api_hash and
            self.telegram_phone
        )


# Global settings instance
settings = Settings()
