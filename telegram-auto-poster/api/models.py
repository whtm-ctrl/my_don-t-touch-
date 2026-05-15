"""
SQLAlchemy ORM models for the Telegram Auto Poster application.
"""

from sqlalchemy import Column, String, Boolean, Integer, Float, Text, DateTime, ForeignKey, UniqueConstraint, Time
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timezone
import uuid

Base = declarative_base()


class SourceChannel(Base):
    """Model for source channels to scrape messages from."""
    
    __tablename__ = "source_channels"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(255))
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_scraped_at = Column(DateTime(timezone=True))
    messages_count = Column(Integer, default=0)
    
    posts = relationship("Post", back_populates="source_channel", cascade="all, delete-orphan")
    analytics = relationship("Analytics", back_populates="source_channel", cascade="all, delete-orphan")


class TargetChannel(Base):
    """Model for target channels to post messages to."""
    
    __tablename__ = "target_channels"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(String(255), unique=True, nullable=False)
    title = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    posted_messages = relationship("PostedMessage", back_populates="target_channel", cascade="all, delete-orphan")


class Post(Base):
    """Model for scraped posts from source channels."""
    
    __tablename__ = "posts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_channel_id = Column(UUID(as_uuid=True), ForeignKey("source_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, nullable=False)
    text = Column(Text)
    media_type = Column(String(50))
    media_path = Column(String(500))
    views_count = Column(Integer, default=0)
    forwards_count = Column(Integer, default=0)
    reactions = Column(JSONB, default=dict)
    similarity_score = Column(Float, default=1.0)
    quality_score = Column(Float, default=0.0)
    status = Column(String(50), default="pending", index=True)  # pending, processed, posted, skipped, failed
    error_message = Column(Text)
    posted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    source_channel = relationship("SourceChannel", back_populates="posts")
    posted_messages = relationship("PostedMessage", back_populates="post", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint("source_channel_id", "message_id", name="uq_source_message"),
    )


class PostedMessage(Base):
    """Model for messages that have been posted to target channels."""
    
    __tablename__ = "posted_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    target_channel_id = Column(UUID(as_uuid=True), ForeignKey("target_channels.id", ondelete="CASCADE"), nullable=False)
    telegram_message_id = Column(Integer)
    status = Column(String(50), default="pending")
    views_count = Column(Integer, default=0)
    forwards_count = Column(Integer, default=0)
    reactions = Column(JSONB, default=dict)
    posted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    post = relationship("Post", back_populates="posted_messages")
    target_channel = relationship("TargetChannel", back_populates="posted_messages")


class BlacklistWord(Base):
    """Model for blacklist words used in filtering."""
    
    __tablename__ = "blacklist_words"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    word = Column(String(255), nullable=False)
    is_regex = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WhitelistWord(Base):
    """Model for whitelist words used in filtering."""
    
    __tablename__ = "whitelist_words"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    word = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SchedulerSettings(Base):
    """Model for scheduler configuration settings."""
    
    __tablename__ = "scheduler_settings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weekday_start_time = Column(Time, default=datetime.strptime("09:00:00", "%H:%M:%S").time())
    weekday_end_time = Column(Time, default=datetime.strptime("22:00:00", "%H:%M:%S").time())
    weekend_start_time = Column(Time, default=datetime.strptime("10:00:00", "%H:%M:%S").time())
    weekend_end_time = Column(Time, default=datetime.strptime("23:00:00", "%H:%M:%S").time())
    max_posts_per_hour = Column(Integer, default=5)
    max_posts_per_day = Column(Integer, default=50)
    min_interval_seconds = Column(Integer, default=300)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Analytics(Base):
    """Model for daily analytics data."""
    
    __tablename__ = "analytics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime(timezone=True).with_variant(DateTime, "sqlite"), nullable=False, index=True)
    source_channel_id = Column(UUID(as_uuid=True), ForeignKey("source_channels.id", ondelete="CASCADE"), nullable=False)
    posts_scraped = Column(Integer, default=0)
    posts_posted = Column(Integer, default=0)
    posts_skipped = Column(Integer, default=0)
    total_views = Column(Integer, default=0)
    total_forwards = Column(Integer, default=0)
    avg_quality_score = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    source_channel = relationship("SourceChannel", back_populates="analytics")
    
    __table_args__ = (
        UniqueConstraint("date", "source_channel_id", name="uq_date_source"),
    )


class ErrorLog(Base):
    """Model for error logging."""
    
    __tablename__ = "error_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name = Column(String(100), nullable=False)
    error_type = Column(String(100))
    error_message = Column(Text, nullable=False)
    stack_trace = Column(Text)
    context = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class DuplicateCache(Base):
    """Model for caching text embeddings for duplicate detection."""
    
    __tablename__ = "duplicate_cache"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text_hash = Column(String(64), unique=True, nullable=False, index=True)
    embedding = Column(String)  # Stored as string representation of array
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
