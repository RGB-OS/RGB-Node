# Setup & Running Guide

Quick guide to get RGB Node up and running.

## Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for local development)
- PostgreSQL 15+ (or use Docker)

## Quick Start (Docker Compose)

### 1. Configure Environment

Copy `env.example` to `.env` and update if needed:

```bash
cp env.example .env
```

Default values work for local development.

### 2. Start All Services

```bash
docker compose up -d
```

This starts:
- **PostgreSQL** (port 5432) - Database for refresh queue and watchers
- **FastAPI service** (port 8000) - Main RGB Node API
- **Refresh worker** - Background process for wallet state sync

### 3. Verify Services

```bash
# Check all services are running
docker compose ps

# Check API is accessible
curl http://localhost:8000/docs

# Check database tables
docker compose exec postgres psql -U postgres -d rgb_node -c "\dt"
```

## Running Manually (Without Docker)

### 1. Start PostgreSQL

```bash
# Using Docker
docker run -d --name postgres-rgb \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=rgb_node \
  -p 5432:5432 \
  postgres:15-alpine

# Initialize schema
psql -U postgres -d rgb_node < migrations/001_initial_schema.sql
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start FastAPI

```bash
uvicorn main:app --reload
```

### 4. Start Refresh Worker (separate terminal)

```bash
python -m workers.refresh_worker
```

## Environment Variables

Key variables in `.env`:

```bash
# Network
NETWORK=3  # 1=mainnet, 3=testnet
PROXY_ENDPOINT=rpcs://proxy.iriswallet.com/0.2/json-rpc
INDEXER_URL=tcp://electrum.rgbtools.org:50041

# PostgreSQL
POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/rgb_node

# Worker
REFRESH_INTERVAL=100  # Seconds between invoice refresh checks
MAX_REFRESH_RETRIES=10
POLL_INTERVAL=1  # Seconds between queue polls
```

## Scaling Workers

Run multiple workers for higher throughput:

```bash
docker compose up --scale refresh-worker=3
```

## Database Management

### Clean Up Tables

```bash
# Using Python script
python scripts/cleanup_tables.py --method truncate

# Or direct SQL
docker compose exec postgres psql -U postgres -d rgb_node -c \
  "TRUNCATE TABLE refresh_jobs, refresh_watchers, wallet_locks RESTART IDENTITY CASCADE;"
```

### Check Status

```bash
# Active watchers
docker compose exec postgres psql -U postgres -d rgb_node -c \
  "SELECT * FROM refresh_watchers WHERE status='watching';"

# Pending jobs
docker compose exec postgres psql -U postgres -d rgb_node -c \
  "SELECT COUNT(*) FROM refresh_jobs WHERE status='pending';"
```

## Troubleshooting

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker compose exec postgres pg_isready -U postgres

# Check connection string
docker compose logs thunderlink-python | grep POSTGRES
```

### Worker Not Processing Jobs

```bash
# Check worker logs
docker compose logs refresh-worker

# Check for stuck jobs
docker compose exec postgres psql -U postgres -d rgb_node -c \
  "SELECT * FROM refresh_jobs WHERE status='processing' AND processed_at < NOW() - INTERVAL '5 minutes';"
```

### Port Conflicts

If port 5432 is already in use:

```bash
# Stop local PostgreSQL
brew services stop postgresql@15  # macOS
# or
sudo systemctl stop postgresql   # Linux

# Or change port in docker-compose.yml
```

## API Documentation

Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

- **`/wallet/sync`**: Performs immediate wallet sync (does not enqueue background job)
- **`/wallet/sync-job`**: Enqueues a background sync job for processing by workers
- **`/wallet/refresh`**: Manually refresh wallet state
- **`/wallet/blindreceive`**: Create blind receive invoice (triggers background refresh job)
- **`/wallet/witnessreceive`**: Create witness receive invoice (triggers background refresh job)

## Next Steps

- See [REFRESH_FLOW.md](./REFRESH_FLOW.md) to understand how the refresh system works
- See [README.md](./README.md) for API usage and architecture


