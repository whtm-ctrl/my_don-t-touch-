# Telegram Auto Poster

Production-ready solution for auto-filling Telegram channels with content from source channels.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Scraper   │────▶│    Redis    │────▶│    n8n      │
│  (Telethon) │     │   (Queue)   │     │  (AI/Post)  │
└──────┬──────┘     └─────────────┘     └──────┬──────┘
       │                                        │
       ▼                                        ▼
┌─────────────┐                          ┌─────────────┐
│ PostgreSQL  │◀────────────────────────▶│  Telegram   │
│  (Storage)  │                          │   Channels  │
└──────┬──────┘                          └─────────────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│    API      │────▶│  Dashboard  │
│  (FastAPI)  │     │   (React)   │
└─────────────┘     └─────────────┘
```

## Features

- **MTProto Scraper**: Read messages from multiple Telegram channels
- **Content Filtering**: Blacklist/whitelist, duplicate detection, quality scoring
- **Media Processing**: Watermarking, compression, format conversion
- **Scheduler**: Weekday/weekend schedules, rate limits, posting intervals
- **n8n Integration**: AI processing via webhooks with retry queue
- **Analytics**: Track views, forwards, engagement metrics
- **Dashboard**: React UI for management
- **Monitoring**: Grafana + Prometheus

## Quick Start

1. Clone the repository:
```bash
cd telegram-auto-poster
```

2. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. Get Telegram credentials from https://my.telegram.org:
   - API ID
   - API Hash
   - Phone number

4. Start all services:
```bash
docker-compose up -d
```

5. Access services:
   - Dashboard: http://localhost:3000
   - API: http://localhost:8000
   - Grafana: http://localhost:3001 (admin/admin)
   - Prometheus: http://localhost:9090

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| TELEGRAM_API_ID | Telegram API ID | Yes |
| TELEGRAM_API_HASH | Telegram API Hash | Yes |
| TELEGRAM_PHONE | Phone number | Yes |
| BOT_TOKEN | Bot token for notifications | No |
| N8N_WEBHOOK_URL | n8n webhook URL | No |
| TARGET_CHANNEL_ID | Target channel for posting | No |

### API Endpoints

- `GET /health` - Health check
- `POST /source-channels` - Add source channel
- `GET /source-channels` - List source channels
- `DELETE /source-channels/{id}` - Remove source channel
- `POST /blacklist` - Add blacklist word
- `GET /blacklist` - List blacklist words
- `GET /scheduler-settings` - Get scheduler config
- `PUT /scheduler-settings` - Update scheduler config
- `GET /posts` - List posts
- `GET /analytics/daily` - Get analytics
- `GET /stats/summary` - Get summary stats

## Project Structure

```
telegram-auto-poster/
├── docker-compose.yml
├── .env.example
├── init.sql
├── scraper/
│   ├── Dockerfile
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── filters.py
│   ├── media_handler.py
│   ├── scheduler.py
│   └── n8n_client.py
├── api/
│   ├── Dockerfile
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   └── models.py
├── dashboard/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       └── index.css
└── grafana/
    └── provisioning/
```

## n8n Workflow Example

Create an n8n workflow with:
1. Webhook node (POST)
2. OpenAI/Groq node for text processing
3. Telegram node for posting
4. Error handling

## Monitoring

- **Prometheus**: Metrics collection at `/metrics` endpoints
- **Grafana**: Pre-configured dashboards at port 3001

## License

MIT
