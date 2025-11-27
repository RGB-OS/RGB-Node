# Refresh Flow

How the automatic wallet state refresh system works.

## Overview

RGB Node automatically syncs wallet state when:
- **Invoices are created** (`/wallet/blindreceive`, `/wallet/witnessreceive`)
- **Assets are sent** (`/wallet/sendend`)

The system uses PostgreSQL to queue refresh jobs and a background worker to process them.

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌──────────────┐
│   FastAPI   │────────▶│  PostgreSQL  │◀────────│   Worker     │
│   (API)     │ Enqueue │   (Queue)    │  Poll   │  (Processor) │
└─────────────┘         └──────────────┘         └──────────────┘
      │                         │                         │
      │                         │                         │
      └─────────────────────────┴─────────────────────────┘
                    HTTP Calls to /wallet/refresh
```

## Flow Types

### 1. Invoice Watching Flow

**Trigger**: Invoice created via `/wallet/blindreceive` or `/wallet/witnessreceive`

**Steps**:
1. API creates invoice and enqueues refresh job with `recipient_id`
2. Worker picks up job and starts watching
3. Worker continuously:
   - Checks transfer status via `/wallet/listtransfers`
   - Refreshes wallet via `/wallet/refresh` every `REFRESH_INTERVAL` seconds
   - Monitors until transfer reaches terminal state (`SETTLED`, `FAILED`, or expired)
4. Watcher stops when transfer completes or expires

**Database**:
- Job stored in `refresh_jobs` table
- Watcher state in `refresh_watchers` table (tracks status, refresh count, expiration)

### 2. Asset Send Flow

**Trigger**: Asset sent via `/wallet/sendend`

**Steps**:
1. API finalizes transfer and enqueues refresh job (no `recipient_id`)
2. Worker picks up job and refreshes wallet immediately
3. Worker retries with exponential backoff if refresh fails (up to `MAX_RETRIES`)
4. Job completes after successful refresh

**Database**:
- Job stored in `refresh_jobs` table
- No watcher created (one-time refresh)

## Components

### Queue (`src/queue/`)

- **`jobs.py`**: Job enqueueing, dequeuing, status updates
- **`watchers.py`**: Watcher state management (create, update, stop)
- **`locks.py`**: Wallet locks to prevent concurrent refreshes
- **`recovery.py`**: Automatic recovery of active watchers on startup

### Worker (`workers/`)

- **`refresh_worker.py`**: Main loop that polls PostgreSQL for jobs (with parallel processing)
- **`processors/job_processor.py`**: Routes jobs to appropriate handler
- **`processors/unified_handler.py`**: Unified wallet handler - processes all assets and transfers
- **`processors/transfer_watcher.py`**: Unified transfer watcher - watches transfers until completion
- **`api/client.py`**: HTTP client for calling FastAPI endpoints

## Database Schema

### `refresh_jobs`
- Job queue with status tracking (`pending`, `processing`, `completed`, `failed`)
- Stores wallet credentials, job metadata, retry info

### `refresh_watchers`
- Active invoice watchers
- Tracks `recipient_id`, status, refresh count, expiration
- Unique constraint on `(xpub_van, recipient_id)`

### `wallet_locks`
- Prevents concurrent refreshes of same wallet
- Auto-expires after TTL (30 seconds)

## Configuration

Key settings in `.env`:

```bash
REFRESH_INTERVAL=100      # Seconds between invoice refresh checks
MAX_REFRESH_RETRIES=10    # Max retries for asset send refresh
RETRY_DELAY_BASE=5        # Base delay for exponential backoff (seconds)
POLL_INTERVAL=1           # Seconds between queue polls
WATCHER_TTL=86400        # Watcher expiration (24 hours)
```

## Recovery

On application startup:
1. Database schema initializes automatically
2. Active watchers are recovered from `refresh_watchers` table
3. Refresh jobs are re-enqueued for active watchers
4. Workers resume watching invoices seamlessly

This ensures continuity after restarts or crashes.

## Job Lifecycle

```
1. API enqueues job → status: 'pending'
2. Worker dequeues job → status: 'processing'
3. Worker processes job:
   - Invoice watcher: runs until transfer completes
   - Asset send: refreshes with retry logic
4. Job completes → status: 'completed' or 'failed'
```

## Monitoring

Check watcher status:
```bash
# Active watchers
SELECT * FROM refresh_watchers WHERE status='watching';

# Job queue
SELECT status, COUNT(*) FROM refresh_jobs GROUP BY status;
```

## Error Handling

- **Queue failures**: Logged but don't fail API requests
- **Refresh failures**: Retried with exponential backoff
- **Watcher errors**: Logged, watcher continues until terminal state
- **Lock conflicts**: Worker skips refresh if wallet is locked


