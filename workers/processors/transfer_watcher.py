"""
Unified transfer watcher.

Watches transfers (send, receive, expired) until they're settled, failed, or expired.
Single unified code path for all transfer types.
"""
import time
import logging
from typing import Dict, Any, Optional
from workers.config import REFRESH_INTERVAL
from workers.api.client import get_api_client
from workers.processors.transfer_utils import is_transfer_completed, is_transfer_expired
from src.queue import (
    create_watcher,
    update_watcher_status,
    stop_watcher,
    get_watcher_status,
    acquire_wallet_lock,
    release_wallet_lock,
    enqueue_refresh_job,
)

logger = logging.getLogger(__name__)


def _get_transfer_identifier(transfer: Dict[str, Any], job: Dict[str, Any]) -> Optional[str]:
    """
    Get transfer identifier from transfer or job.
    
    Uses recipient_id (required for watchers).
    
    Args:
        transfer: Transfer dictionary (may be None)
        job: Job dictionary
        
    Returns:
        recipient_id if available, None otherwise
    """
    if transfer:
        recipient_id = transfer.get('recipient_id')
        if recipient_id:
            return recipient_id
    
    # Fallback to job data
    recipient_id = job.get('recipient_id')
    if recipient_id:
        return recipient_id
    
    return None


def watch_transfer(
    job: Dict[str, Any],
    recipient_id: str,
    asset_id: Optional[str],
    shutdown_flag: callable
) -> None:
    """
    Watch a transfer until it's settled, failed, or expired.
    
    Unified handler for all transfer types (send, receive, expired).
    Continuously polls transfer status and refreshes wallet state
    until the transfer reaches a terminal state.
    
    Args:
        job: Job dictionary with wallet credentials
        recipient_id: Recipient ID (required - unique identifier for the transfer)
        asset_id: Asset ID (optional)
        shutdown_flag: Callable that returns True if shutdown requested
    """
    xpub_van = job['xpub_van']
    refresh_count = 0
    
    # Create watcher entry when watcher starts (only if it doesn't exist)
    # If watcher already exists, preserve its expiration (e.g., 180s for invoice_created without asset_id)
    try:
        existing_watcher = get_watcher_status(xpub_van, recipient_id)
        if not existing_watcher:
            # Only create if it doesn't exist - this preserves expiration set by job_processor
            create_watcher(
                xpub_van=job['xpub_van'],
                xpub_col=job['xpub_col'],
                master_fingerprint=job['master_fingerprint'],
                recipient_id=recipient_id,
                asset_id=asset_id
            )
            logger.info(
                f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Created watcher entry "
                f"for transfer {recipient_id}"
            )
        else:
            logger.debug(
                f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Watcher already exists "
                f"for transfer {recipient_id}, preserving expiration"
            )
    except Exception as e:
        logger.warning(
            f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Failed to create watcher entry: {e}"
        )
    
    logger.info(
        f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Started watching "
        f"transfer {recipient_id}, asset_id={asset_id}"
    )
    
    api_client = get_api_client()
    
    # Create job dict for API calls (needs recipient_id for get_transfer_status)
    transfer_job = job.copy()
    transfer_job['recipient_id'] = recipient_id
    if asset_id:
        transfer_job['asset_id'] = asset_id
    
    try:
        while not shutdown_flag():
            try:
                # Check if watcher has expired (for invoice_created without asset_id)
                if not asset_id:
                    watcher = get_watcher_status(xpub_van, recipient_id)
                    if watcher:
                        expires_at = watcher.get('expires_at')
                        if expires_at:
                            # expires_at is already normalized to Unix timestamp
                            if isinstance(expires_at, int):
                                current_time = int(time.time())
                                time_until_expiry = expires_at - current_time
                                logger.info(
                                    f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                    f"Watcher expires in {time_until_expiry} seconds (expires_at={expires_at}, current={current_time})"
                                )
                                if current_time >= expires_at:
                                    # Watcher expired after 3 min, trigger sync job
                                    logger.info(
                                        f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                        f"Watcher for {recipient_id} expired (3 min), triggering sync job"
                                    )
                                    try:
                                        enqueue_refresh_job(
                                            xpub_van=job['xpub_van'],
                                            xpub_col=job['xpub_col'],
                                            master_fingerprint=job['master_fingerprint'],
                                            trigger="sync"
                                        )
                                        logger.info(
                                            f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                            f"Triggered sync job after watcher expiration"
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"[TransferWatcher] Failed to trigger sync job: {e}", exc_info=True
                                        )
                                    update_watcher_status(xpub_van, recipient_id, 'expired', refresh_count)
                                    stop_watcher(xpub_van, recipient_id)
                                    return
                
                # Get transfer status
                transfer = api_client.get_transfer_status(transfer_job)
                
                if not transfer:
                    logger.info(
                        f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Transfer not found for {recipient_id}, continuing..."
                    )
                else:
                    status = transfer.get('status')
                    kind = transfer.get('kind')
                    
                    # Check for terminal states
                    if is_transfer_completed(transfer):
                        # Normalize status to string for storage
                        if hasattr(status, 'name'):
                            final_status = status.name.lower()
                        elif isinstance(status, int):
                            # TransferStatus: SETTLED=2, FAILED=3
                            final_status = 'settled' if status == 2 else 'failed'
                        else:
                            final_status = str(status).lower()
                        update_watcher_status(xpub_van, recipient_id, final_status, refresh_count)
                        stop_watcher(xpub_van, recipient_id)
                        logger.info(
                            f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                            f"Stopped watching transfer {recipient_id} - status: {status}"
                        )
                        return
                    
                    # Check for expiration
                    if is_transfer_expired(transfer):
                        update_watcher_status(xpub_van, recipient_id, 'expired', refresh_count)
                        stop_watcher(xpub_van, recipient_id)
                        logger.info(
                            f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                            f"Stopped watching transfer {recipient_id} - expired"
                        )
                        return
                
                # Refresh wallet state (with lock to prevent concurrent refreshes)
                try:
                    if acquire_wallet_lock(xpub_van, ttl=30):
                        try:
                            api_client.refresh_wallet(job)
                            refresh_count += 1
                            update_watcher_status(
                                xpub_van, recipient_id, "watching", refresh_count
                            )
                        finally:
                            release_wallet_lock(xpub_van)
                    else:
                        logger.debug(
                            f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                            f"Wallet is being refreshed by another worker, skipping this cycle"
                        )
                except Exception as e:
                    logger.warning(
                        f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Refresh failed for transfer {recipient_id}: {e}"
                    )
                
                time.sleep(REFRESH_INTERVAL)
                
            except Exception as e:
                logger.error(
                    f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                    f"Error watching transfer {recipient_id}: {e}", exc_info=True
                )
                time.sleep(REFRESH_INTERVAL)
    finally:
        if shutdown_flag():
            logger.info(
                f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                f"Shutting down watcher for transfer {recipient_id}"
            )

