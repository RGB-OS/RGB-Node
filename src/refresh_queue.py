"""
PostgreSQL-based refresh job queue for wallet state synchronization.

This is a compatibility layer that re-exports functions from the refactored queue module.
Prefer importing directly from src.queue for new code.
"""
from src.queue import (
    enqueue_refresh_job,
    get_job_status,
    get_watcher_status,
    update_watcher_status,
    stop_watcher,
    acquire_wallet_lock,
    release_wallet_lock,
    init_database,
    recover_active_watchers,
)

__all__ = [
    'enqueue_refresh_job',
    'get_job_status',
    'get_watcher_status',
    'update_watcher_status',
    'stop_watcher',
    'acquire_wallet_lock',
    'release_wallet_lock',
    'init_database',
    'recover_active_watchers',
]

