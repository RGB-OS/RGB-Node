# Refresh Flow

How the automatic wallet state refresh system works.

## Overview

RGB Node automatically syncs wallet state when:
- **Invoices are created** (`/wallet/blindreceive`, `/wallet/witnessreceive`)
- **Assets are sent** (`/wallet/sendend`)
- **Wallet is synced** (`/wallet/sync`)

The system uses PostgreSQL to queue refresh jobs and a process-based orchestrator that spawns dedicated wallet worker processes.

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌──────────────────┐
│   FastAPI   │────────▶│  PostgreSQL  │◀────────│ Refresh Worker   │
│   (API)     │ Enqueue │   (Queue)    │  Poll   │ (Orchestrator)    │
└─────────────┘         └──────────────┘         └──────────────────┘
      │                         │                         │
      │                         │                         │
      │                         │                         ├──▶ Wallet Worker 1 (xpub_van_1)
      │                         │                         │    - Processes jobs sequentially
      │                         │                         │    - Processes watchers sequentially
      │                         │                         │
      │                         │                         ├──▶ Wallet Worker 2 (xpub_van_2)
      │                         │                         │    - Processes jobs sequentially
      │                         │                         │    - Processes watchers sequentially
      │                         │                         │
      │                         │                         └──▶ Wallet Worker N (xpub_van_N)
      │                         │                              (up to MAX_WALLET_PROCESSES)
      │                         │
      └─────────────────────────┴─────────────────────────┘
                    HTTP Calls to /wallet/refresh
```

## Key Concepts

### Jobs
- **Unique job ID per job** (job_id = UUID4, truly unique)
- Jobs are stored in `refresh_jobs` table
- Status: `pending` → `processing` → `completed`/`failed`
- Multiple jobs can exist for the same wallet (e.g., sync, send, invoice_created)
- Jobs include optional `recipient_id` and `asset_id` fields (for invoice_created triggers)

### Watchers
- **One watcher per transfer** (unique by xpub_van + recipient_id)
- Watchers are stored in `refresh_watchers` table
- Status: `watching` → `settled`/`failed`/`expired`
- Watchers monitor transfers until completion or expiration

### Wallet Locks
- **Prevents concurrent refreshes** of the same wallet
- Stored in `wallet_locks` table
- Auto-expires after 30 seconds (TTL)
- Used by both jobs and watchers when refreshing wallet state

## Flow Types

### 1. Invoice Created Flow (with asset_id)

**Trigger**: Invoice created via `/wallet/blindreceive` or `/wallet/witnessreceive` (with asset_id)

**Steps**:
1. API creates invoice and enqueues job with `trigger="invoice_created"`, `recipient_id`, `asset_id`
2. Orchestrator detects wallet with pending job and spawns wallet worker process
3. Wallet worker dequeues job and calls `process_wallet_unified()`:
   - Acquires wallet lock
   - Refreshes wallet state
   - Lists all assets
   - For each asset, lists transfers
   - For incomplete transfers, creates watchers (if they don't exist)
   - Releases wallet lock
4. Job completes, wallet worker processes watchers:
   - For each active watcher, calls `watch_transfer()`
   - Watcher continuously monitors transfer status
   - Refreshes wallet every `REFRESH_INTERVAL` seconds (with lock)
   - Stops when transfer reaches terminal state

**Database**:
- Job in `refresh_jobs` table (with recipient_id and asset_id)
- Watcher entries in `refresh_watchers` table for incomplete transfers

### 2. Invoice Created Flow (without asset_id)

**Trigger**: Invoice created via `/wallet/blindreceive` or `/wallet/witnessreceive` (without asset_id)

**Steps**:
1. API creates invoice and enqueues job with `trigger="invoice_created"`, `recipient_id`, `asset_id=None`
2. Orchestrator spawns wallet worker process
3. Wallet worker processes job:
   - Creates watcher with 3 min expiration (180 seconds)
   - Job completes immediately
4. Wallet worker processes watcher:
   - Watcher monitors transfer and refreshes wallet every `REFRESH_INTERVAL` seconds
   - After 3 minutes, watcher expires and triggers a sync job
   - Sync job refreshes wallet and creates watchers for any incomplete transfers found

**Database**:
- Job in `refresh_jobs` table (with recipient_id, asset_id=None)
- Watcher in `refresh_watchers` table with 3 min expiration

### 3. Asset Send Flow

**Trigger**: Asset sent via `/wallet/sendend`

**Steps**:
1. API finalizes transfer and enqueues job with `trigger="asset_sent"`
2. Orchestrator spawns wallet worker process
3. Wallet worker processes job:
   - Acquires wallet lock
   - Refreshes wallet state
   - Lists assets and transfers
   - Creates watchers for incomplete transfers
   - Releases wallet lock
4. Job completes, wallet worker processes watchers for any incomplete transfers

**Database**:
- Job in `refresh_jobs` table
- Watcher entries created for incomplete transfers

### 4. Sync Flow

**Trigger**: Sync job enqueued via `/wallet/sync-job` endpoint

**Steps**:
1. API enqueues job with `trigger="sync"` (no immediate wallet sync)
2. Orchestrator spawns wallet worker process
3. Wallet worker processes job:
   - Acquires wallet lock
   - Refreshes wallet state
   - Lists transfers without asset_id first
   - Lists all assets and their transfers
   - Creates watchers for incomplete transfers
   - Releases wallet lock
4. Job completes, wallet worker processes watchers

**Note**: The `/wallet/sync` endpoint only performs an immediate wallet sync and does not enqueue a job. Use `/wallet/sync-job` to trigger background processing.

**Database**:
- Job in `refresh_jobs` table
- Watcher entries created for incomplete transfers

## Process Architecture

### Orchestrator (`refresh_worker.py`)
- **Single process** that monitors the job queue
- Polls PostgreSQL every `POLL_INTERVAL` seconds
- Identifies wallets with:
  - Pending jobs OR
  - Active watchers
- Spawns one wallet worker process per wallet (up to `MAX_WALLET_PROCESSES`)
- Monitors spawned processes and cleans up dead ones
- On startup, recovers active watchers by creating pending jobs

### Wallet Worker (`wallet_worker.py`)
- **Dedicated process per wallet**
- Processes jobs and watchers sequentially for its assigned wallet
- Main loop:
  1. Dequeue and process pending jobs (one at a time)
  2. Process active watchers (one at a time)
  3. Sleep `WALLET_WORKER_POLL_INTERVAL` seconds
  4. Terminates after `WALLET_WORKER_IDLE_TIMEOUT` seconds of no work

### Job Processor (`job_processor.py`)
- Routes jobs to appropriate handlers
- Special handling for `invoice_created` without `asset_id`: creates watcher with 3 min expiration
- All other jobs: calls `process_wallet_unified()`

### Unified Handler (`unified_handler.py`)
- Processes wallet refresh, lists transfers without asset_id, lists assets, lists transfers
- Creates watchers for incomplete transfers
- Handles expired transfers by calling `/wallet/failtransfers` if eligible
- Uses wallet lock to prevent concurrent refreshes

### Transfer Watcher (`transfer_watcher.py`)
- Monitors individual transfers until completion
- Handles transfers that initially lack `asset_id` but acquire one later (searches across all assets)
- Refreshes wallet every `REFRESH_INTERVAL` seconds (with lock)
- Checks for watcher expiration (for invoice_created without asset_id)
- Handles expired transfers by calling `/wallet/failtransfers` if eligible
- Stops when transfer completes, fails, or expires

## Wallet Locking

**When locks are acquired:**
1. **During `process_wallet_unified()`**: Before refreshing wallet (line 81 in unified_handler.py)
2. **During `watch_transfer()`**: Before each wallet refresh (line 202 in transfer_watcher.py)

**Lock behavior:**
- Lock TTL: 30 seconds (default)
- If lock acquisition fails, operation is skipped (logged as debug/warning)
- Locks auto-expire and are cleaned up before each acquisition attempt
- Prevents concurrent refreshes of the same wallet

**Lock conflicts:**
- If a job tries to refresh while a watcher is refreshing → job skips refresh
- If multiple watchers try to refresh simultaneously → only one succeeds, others skip
- If a watcher tries to refresh while a job is processing → watcher skips refresh

## Database Schema

### `refresh_jobs`
- `job_id`: UUID4 (unique per job)
- `xpub_van`, `xpub_col`, `master_fingerprint`: Wallet credentials
- `trigger`: What triggered the job (sync, asset_sent, invoice_created, etc.)
- `recipient_id`: Optional (for invoice_created jobs)
- `asset_id`: Optional (for invoice_created jobs, can be None)
- `status`: pending, processing, completed, failed
- `created_at`, `processed_at`: Timestamps

### `refresh_watchers`
- `xpub_van`, `xpub_col`, `master_fingerprint`: Wallet credentials
- `recipient_id`: Transfer identifier (required)
- `asset_id`: Optional asset ID
- `status`: watching, settled, failed, expired
- `expires_at`: Watcher expiration timestamp
- `refresh_count`: Number of refreshes performed
- Unique constraint on `(xpub_van, recipient_id)`

### `wallet_locks`
- `xpub_van`: Wallet identifier (primary key)
- `locked_at`: When lock was acquired
- `expires_at`: When lock expires (TTL: 30 seconds)
- Auto-expires and cleaned up before each acquisition

## Configuration

Key settings in `.env`:

```bash
# Worker Configuration
REFRESH_INTERVAL=30           # Seconds between wallet refreshes in watchers
MAX_REFRESH_RETRIES=10        # Max retries for failed refreshes
RETRY_DELAY_BASE=5            # Base delay for exponential backoff (seconds)
POLL_INTERVAL=1               # Seconds between queue polls (orchestrator)
WATCHER_TTL=86400            # Default watcher expiration (24 hours)

# Wallet Worker Configuration
WALLET_WORKER_IDLE_TIMEOUT=60 # Seconds before terminating idle process
WALLET_WORKER_POLL_INTERVAL=5 # Seconds between work checks in wallet worker
MAX_WALLET_PROCESSES=50       # Maximum concurrent wallet worker processes

# API Configuration
API_URL=http://localhost:8000 # FastAPI service URL
HTTP_TIMEOUT=60               # HTTP request timeout (seconds)

# PostgreSQL Configuration
POSTGRES_URL=postgresql://... # Database connection string
POSTGRES_MIN_CONNECTIONS=2    # Minimum connection pool size
POSTGRES_MAX_CONNECTIONS=10   # Maximum connection pool size
```

## Recovery

On orchestrator startup:
1. Calls `recover_active_watchers()` which:
   - Finds all active watchers in database
   - Creates pending jobs for wallets with active watchers
   - Ensures watchers resume after restart
2. Orchestrator then spawns wallet worker processes for wallets with pending jobs or active watchers

This ensures continuity after restarts or crashes.

## Job Lifecycle

```
1. API enqueues job → status: 'pending'
2. Orchestrator detects wallet with pending job
3. Orchestrator spawns wallet worker process (if not already running and under MAX_WALLET_PROCESSES limit)
4. Wallet worker dequeues job → status: 'processing'
5. Wallet worker processes job:
   - All jobs: Calls process_wallet_unified() which:
     - Lists transfers without asset_id first
     - Lists all assets and their transfers
     - Creates watchers for incomplete transfers
     - Handles expired transfers (calls failtransfers if eligible)
6. Job completes → status: 'completed' or 'failed'
7. Wallet worker processes active watchers
8. Wallet worker terminates after idle timeout
```

## Monitoring

Check system status:
```bash
# Active wallet processes
SELECT COUNT(*) FROM wallet_locks;

# Active watchers
SELECT COUNT(*) FROM refresh_watchers WHERE status='watching';

# Job queue status
SELECT status, COUNT(*) FROM refresh_jobs GROUP BY status;

# Pending jobs by wallet
SELECT xpub_van, COUNT(*) FROM refresh_jobs WHERE status='pending' GROUP BY xpub_van;
```

## Transfer Cancellation

Expired transfers are automatically cancelled (failed) if they meet specific criteria:

**Cancellation Conditions**:
- Transfer status is `WAITING_COUNTERPARTY` (0)
- Transfer has an expiration timestamp that is in the past
- Either:
  - Transfer kind is `RECEIVE_BLIND` (1), OR
  - `expiration + DURATION_RCV_TRANSFER < now`

**Implementation**:
- Checked in `transfer_utils.can_cancel_transfer()`
- Called from `unified_handler.py` during initial processing
- Called from `transfer_watcher.py` when transfer expires during watching
- Uses `/wallet/failtransfers` API endpoint with `batch_transfer_idx`

## Error Handling

- **Queue failures**: Logged but don't fail API requests
- **Refresh failures**: Retried with exponential backoff (up to MAX_RETRIES)
- **Watcher errors**: Logged, watcher continues until terminal state
- **Lock conflicts**: Operation skipped, logged as debug/warning
- **Process failures**: Orchestrator detects and respawns wallet worker
- **Process limit reached**: New wallets skipped until processes free up
- **Transfer cancellation failures**: Logged but don't stop watcher processing
