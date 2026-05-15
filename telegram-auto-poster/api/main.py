"""
FastAPI application for Telegram Auto Poster management.
Provides REST API for channel management, settings, and analytics.
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime, timezone
import structlog

from config import settings
from database import get_db, init_db, close_db
from models import (
    SourceChannel, TargetChannel, Post, PostedMessage,
    BlacklistWord, WhitelistWord, SchedulerSettings,
    Analytics, ErrorLog
)
from pydantic import BaseModel, Field

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
)

logger = structlog.get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Telegram Auto Poster API",
    description="API for managing Telegram channel auto-posting",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Models
class SourceChannelCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    title: Optional[str] = None
    is_active: bool = True


class SourceChannelResponse(BaseModel):
    id: str
    username: str
    title: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_scraped_at: Optional[datetime]
    messages_count: int

    class Config:
        from_attributes = True


class TargetChannelCreate(BaseModel):
    channel_id: str = Field(..., min_length=1, max_length=255)
    title: Optional[str] = None
    is_active: bool = True


class TargetChannelResponse(BaseModel):
    id: str
    channel_id: str
    title: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BlacklistWordCreate(BaseModel):
    word: str = Field(..., min_length=1, max_length=255)
    is_regex: bool = False
    is_active: bool = True


class BlacklistWordResponse(BaseModel):
    id: str
    word: str
    is_regex: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WhitelistWordCreate(BaseModel):
    word: str = Field(..., min_length=1, max_length=255)
    is_active: bool = True


class WhitelistWordResponse(BaseModel):
    id: str
    word: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SchedulerSettingsUpdate(BaseModel):
    weekday_start_time: Optional[str] = None
    weekday_end_time: Optional[str] = None
    weekend_start_time: Optional[str] = None
    weekend_end_time: Optional[str] = None
    max_posts_per_hour: Optional[int] = Field(None, ge=1, le=100)
    max_posts_per_day: Optional[int] = Field(None, ge=1, le=1000)
    min_interval_seconds: Optional[int] = Field(None, ge=60)
    is_active: Optional[bool] = None


class SchedulerSettingsResponse(BaseModel):
    id: str
    weekday_start_time: str
    weekday_end_time: str
    weekend_start_time: str
    weekend_end_time: str
    max_posts_per_hour: int
    max_posts_per_day: int
    min_interval_seconds: int
    is_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class PostResponse(BaseModel):
    id: str
    source_channel_id: str
    message_id: int
    text: Optional[str]
    media_type: Optional[str]
    status: str
    quality_score: float
    created_at: datetime
    posted_at: Optional[datetime]

    class Config:
        from_attributes = True


class AnalyticsResponse(BaseModel):
    date: datetime
    posts_scraped: int
    posts_posted: int
    posts_skipped: int
    total_views: int
    avg_quality_score: float

    class Config:
        from_attributes = True


class ErrorLogResponse(BaseModel):
    id: str
    service_name: str
    error_type: Optional[str]
    error_message: str
    created_at: datetime

    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    services: dict


# Startup/Shutdown events
@app.on_event("startup")
async def startup_event():
    await init_db()
    logger.info("API started")


@app.on_event("shutdown")
async def shutdown_event():
    await close_db()
    logger.info("API stopped")


@app.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(1))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        timestamp=datetime.now(timezone.utc),
        services={"database": db_status, "redis": "unknown"}
    )


@app.post("/source-channels", response_model=SourceChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_source_channel(channel: SourceChannelCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(SourceChannel).where(SourceChannel.username == channel.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Channel {channel.username} already exists")

    db_channel = SourceChannel(**channel.model_dump())
    db.add(db_channel)
    await db.flush()
    await db.refresh(db_channel)
    return db_channel


@app.get("/source-channels", response_model=List[SourceChannelResponse])
async def list_source_channels(
    skip: int = 0, limit: int = 100, is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(SourceChannel)
    if is_active is not None:
        query = query.where(SourceChannel.is_active == is_active)
    query = query.offset(skip).limit(limit).order_by(SourceChannel.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@app.get("/source-channels/{channel_id}", response_model=SourceChannelResponse)
async def get_source_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SourceChannel).where(SourceChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@app.put("/source-channels/{channel_id}", response_model=SourceChannelResponse)
async def update_source_channel(channel_id: str, channel_update: SourceChannelCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SourceChannel).where(SourceChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    for field, value in channel_update.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    await db.flush()
    await db.refresh(channel)
    return channel


@app.delete("/source-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SourceChannel).where(SourceChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(channel)
    await db.flush()


@app.post("/target-channels", response_model=TargetChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_target_channel(channel: TargetChannelCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(TargetChannel).where(TargetChannel.channel_id == channel.channel_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Target channel {channel.channel_id} already exists")
    db_channel = TargetChannel(**channel.model_dump())
    db.add(db_channel)
    await db.flush()
    await db.refresh(db_channel)
    return db_channel


@app.get("/target-channels", response_model=List[TargetChannelResponse])
async def list_target_channels(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    query = select(TargetChannel).offset(skip).limit(limit).order_by(TargetChannel.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@app.delete("/target-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TargetChannel).where(TargetChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(channel)
    await db.flush()


@app.post("/blacklist", response_model=BlacklistWordResponse, status_code=status.HTTP_201_CREATED)
async def create_blacklist_word(word: BlacklistWordCreate, db: AsyncSession = Depends(get_db)):
    db_word = BlacklistWord(**word.model_dump())
    db.add(db_word)
    await db.flush()
    await db.refresh(db_word)
    return db_word


@app.get("/blacklist", response_model=List[BlacklistWordResponse])
async def list_blacklist_words(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BlacklistWord).order_by(BlacklistWord.created_at.desc()))
    return result.scalars().all()


@app.delete("/blacklist/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blacklist_word(word_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BlacklistWord).where(BlacklistWord.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(status_code=404, detail="Word not found")
    await db.delete(word)
    await db.flush()


@app.post("/whitelist", response_model=WhitelistWordResponse, status_code=status.HTTP_201_CREATED)
async def create_whitelist_word(word: WhitelistWordCreate, db: AsyncSession = Depends(get_db)):
    db_word = WhitelistWord(**word.model_dump())
    db.add(db_word)
    await db.flush()
    await db.refresh(db_word)
    return db_word


@app.get("/whitelist", response_model=List[WhitelistWordResponse])
async def list_whitelist_words(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WhitelistWord).order_by(WhitelistWord.created_at.desc()))
    return result.scalars().all()


@app.delete("/whitelist/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_whitelist_word(word_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WhitelistWord).where(WhitelistWord.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(status_code=404, detail="Word not found")
    await db.delete(word)
    await db.flush()


@app.get("/scheduler-settings", response_model=SchedulerSettingsResponse)
async def get_scheduler_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SchedulerSettings).limit(1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = SchedulerSettings()
        db.add(settings)
        await db.flush()
        await db.refresh(settings)
    return settings


@app.put("/scheduler-settings", response_model=SchedulerSettingsResponse)
async def update_scheduler_settings(settings_update: SchedulerSettingsUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SchedulerSettings).limit(1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = SchedulerSettings()
        db.add(settings)
    for field, value in settings_update.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await db.flush()
    await db.refresh(settings)
    return settings


@app.get("/posts", response_model=List[PostResponse])
async def list_posts(
    skip: int = 0, limit: int = 100, status_filter: Optional[str] = None,
    source_channel_id: Optional[str] = None, db: AsyncSession = Depends(get_db)
):
    query = select(Post)
    if status_filter:
        query = query.where(Post.status == status_filter)
    if source_channel_id:
        query = query.where(Post.source_channel_id == source_channel_id)
    query = query.offset(skip).limit(limit).order_by(Post.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@app.get("/analytics/daily", response_model=List[AnalyticsResponse])
async def get_daily_analytics(days: int = 7, source_channel_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Analytics).where(
        Analytics.date >= datetime.now(timezone.utc).date() - func.make_interval(days=days)
    )
    if source_channel_id:
        query = query.where(Analytics.source_channel_id == source_channel_id)
    query = query.order_by(Analytics.date.desc())
    result = await db.execute(query)
    return result.scalars().all()


@app.get("/errors", response_model=List[ErrorLogResponse])
async def get_error_logs(skip: int = 0, limit: int = 100, service_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(ErrorLog)
    if service_name:
        query = query.where(ErrorLog.service_name == service_name)
    query = query.offset(skip).limit(limit).order_by(ErrorLog.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@app.get("/stats/summary")
async def get_summary_stats(db: AsyncSession = Depends(get_db)):
    source_count = await db.execute(select(func.count(SourceChannel.id)))
    status_counts = await db.execute(select(Post.status, func.count(Post.id)).group_by(Post.status))
    today = datetime.now(timezone.utc).date()
    today_posts = await db.execute(select(func.count(Post.id)).where(func.date(Post.created_at) == today))
    return {
        "source_channels": source_count.scalar(),
        "posts_by_status": {row[0]: row[1] for row in status_counts.all()},
        "posts_today": today_posts.scalar(),
        "timestamp": datetime.now(timezone.utc)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
