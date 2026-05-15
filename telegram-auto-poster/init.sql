-- Telegram Auto Poster Database Schema

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Source Channels Table
CREATE TABLE source_channels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_scraped_at TIMESTAMP WITH TIME ZONE,
    messages_count INTEGER DEFAULT 0
);

-- Target Channels Table
CREATE TABLE target_channels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel_id VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Posts Table (Scraped Messages)
CREATE TABLE posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_channel_id UUID REFERENCES source_channels(id) ON DELETE CASCADE,
    message_id BIGINT NOT NULL,
    text TEXT,
    media_type VARCHAR(50),
    media_path VARCHAR(500),
    views_count INTEGER DEFAULT 0,
    forwards_count INTEGER DEFAULT 0,
    reactions JSONB DEFAULT '{}',
    similarity_score FLOAT DEFAULT 1.0,
    quality_score FLOAT DEFAULT 0.0,
    status VARCHAR(50) DEFAULT 'pending', -- pending, processed, posted, skipped, failed
    error_message TEXT,
    posted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_channel_id, message_id)
);

-- Posted Messages Table (Final posted messages)
CREATE TABLE posted_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
    target_channel_id UUID REFERENCES target_channels(id) ON DELETE CASCADE,
    telegram_message_id BIGINT,
    status VARCHAR(50) DEFAULT 'pending',
    views_count INTEGER DEFAULT 0,
    forwards_count INTEGER DEFAULT 0,
    reactions JSONB DEFAULT '{}',
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Blacklist Words Table
CREATE TABLE blacklist_words (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    word VARCHAR(255) NOT NULL,
    is_regex BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Whitelist Words Table
CREATE TABLE whitelist_words (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    word VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Scheduler Settings Table
CREATE TABLE scheduler_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    weekday_start_time TIME DEFAULT '09:00:00',
    weekday_end_time TIME DEFAULT '22:00:00',
    weekend_start_time TIME DEFAULT '10:00:00',
    weekend_end_time TIME DEFAULT '23:00:00',
    max_posts_per_hour INTEGER DEFAULT 5,
    max_posts_per_day INTEGER DEFAULT 50,
    min_interval_seconds INTEGER DEFAULT 300,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Analytics Table
CREATE TABLE analytics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    source_channel_id UUID REFERENCES source_channels(id) ON DELETE CASCADE,
    posts_scraped INTEGER DEFAULT 0,
    posts_posted INTEGER DEFAULT 0,
    posts_skipped INTEGER DEFAULT 0,
    total_views INTEGER DEFAULT 0,
    total_forwards INTEGER DEFAULT 0,
    avg_quality_score FLOAT DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, source_channel_id)
);

-- Error Logs Table
CREATE TABLE error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name VARCHAR(100) NOT NULL,
    error_type VARCHAR(100),
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    context JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Duplicate Cache Table (for similarity check)
CREATE TABLE duplicate_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    text_hash VARCHAR(64) NOT NULL UNIQUE,
    embedding VECTOR(384),
    post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX idx_source_channels_username ON source_channels(username);
CREATE INDEX idx_source_channels_is_active ON source_channels(is_active);
CREATE INDEX idx_posts_status ON posts(status);
CREATE INDEX idx_posts_created_at ON posts(created_at);
CREATE INDEX idx_posts_source_channel_id ON posts(source_channel_id);
CREATE INDEX idx_posted_messages_post_id ON posted_messages(post_id);
CREATE INDEX idx_analytics_date ON analytics(date);
CREATE INDEX idx_error_logs_created_at ON error_logs(created_at);
CREATE INDEX idx_blacklist_words_is_active ON blacklist_words(is_active);
CREATE INDEX idx_duplicate_cache_text_hash ON duplicate_cache(text_hash);

-- Insert default scheduler settings
INSERT INTO scheduler_settings (
    weekday_start_time, weekday_end_time,
    weekend_start_time, weekend_end_time,
    max_posts_per_hour, max_posts_per_day,
    min_interval_seconds
) VALUES (
    '09:00:00', '22:00:00',
    '10:00:00', '23:00:00',
    5, 50, 300
);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_source_channels_updated_at
    BEFORE UPDATE ON source_channels
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_target_channels_updated_at
    BEFORE UPDATE ON target_channels
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scheduler_settings_updated_at
    BEFORE UPDATE ON scheduler_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
