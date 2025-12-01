"""
PostgreSQL-based refresh job queue module.

Provides job queue, watcher management, and distributed locking functionality.
"""
from src.queue.jobs import (
    enqueue_refresh_job,
    dequeue_refresh_job,
    mark_job_completed,
    mark_job_failed,
    get_job_status,
    get_pending_jobs_for_wallet,
    dequeue_job_for_wallet,
)
from src.queue.watchers import (
    create_watcher,
    get_watcher_status,
    update_watcher_status,
    update_watcher_asset_and_expiration,
    stop_watcher,
    get_active_watchers,
    get_active_watchers_for_wallet,
)
from src.queue.locks import (
    acquire_wallet_lock,
    release_wallet_lock,
)
from src.queue.recovery import (
    recover_active_watchers,
)
from src.queue.schema import (
    init_database,
)

__all__ = [
    # Jobs
    'enqueue_refresh_job',
    'dequeue_refresh_job',
    'mark_job_completed',
    'mark_job_failed',
    'get_job_status',
    'get_pending_jobs_for_wallet',
    'dequeue_job_for_wallet',
    # Watchers
    'create_watcher',
    'get_watcher_status',
    'update_watcher_status',
    'update_watcher_asset_and_expiration',
    'stop_watcher',
    'get_active_watchers',
    'get_active_watchers_for_wallet',
    # Locks
    'acquire_wallet_lock',
    'release_wallet_lock',
    # Recovery
    'recover_active_watchers',
    # Schema
    'init_database',
]

