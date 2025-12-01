"""
Recovery operations.

Handles recovery of active watchers after application restart.
"""
import logging
from src.queue.jobs import enqueue_refresh_job
from src.queue.watchers import get_active_watchers

logger = logging.getLogger(__name__)


def recover_active_watchers() -> int:
    """
    Recover active watchers by re-enqueueing their refresh jobs.
    
    Called on application startup to restore state after restart.
    Ensures continuity of invoice watching after service interruption.
    
    Returns:
        Number of watchers successfully recovered
        
    Example:
        recovered = recover_active_watchers()
        logger.info(f"Recovered {recovered} active watchers on startup")
    """
    try:
        active_watchers = get_active_watchers()
        recovered = 0
        
        for watcher in active_watchers:
            try:
                logger.info(
                    f"Recovering watcher for {watcher['xpub_van']}:{watcher['recipient_id']}"
                )
                
                # Re-enqueue wallet job (watchers will be recreated when wallet is processed)
                enqueue_refresh_job(
                    xpub_van=watcher['xpub_van'],
                    xpub_col=watcher['xpub_col'],
                    master_fingerprint=watcher['master_fingerprint'],
                    trigger='recovery'
                )
                recovered += 1
            except Exception as e:
                logger.error(
                    f"Failed to recover watcher {watcher.get('recipient_id')}: {e}"
                )
        
        logger.info(f"Recovered {recovered} active watchers")
        return recovered
    except Exception as e:
        logger.error(f"Failed to recover active watchers: {e}")
        return 0

