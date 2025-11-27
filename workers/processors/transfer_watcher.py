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
from src.queue import (
    create_watcher,
    update_watcher_status,
    stop_watcher,
    acquire_wallet_lock,
    release_wallet_lock,
)

logger = logging.getLogger(__name__)


def _is_transfer_completed(transfer: Dict[str, Any]) -> bool:
    """Check if transfer is in terminal state."""
    status = transfer.get('status')
    
    # Handle enum object (if not serialized)
    if hasattr(status, 'name'):
        status = status.name
    # Handle enum value (integer) - unlikely but possible
    elif isinstance(status, int):
        # TransferStatus: SETTLED=2, FAILED=3
        return status in [2, 3]
    
    # Handle string (most common from JSON serialization)
    if isinstance(status, str):
        return status.upper() in ['SETTLED', 'FAILED']
    
    return False


def _is_transfer_expired(transfer: Dict[str, Any]) -> bool:
    """Check if transfer has expired."""
    expiration = transfer.get('expiration')
    if not expiration:
        return False
    
    now = int(time.time())
    kind = transfer.get('kind')
    
    # Handle enum object (if not serialized)
    if hasattr(kind, 'name'):
        kind = kind.name
    # Handle enum value (integer)
    elif isinstance(kind, int):
        # TransferKind: RECEIVE_BLIND = 1
        if kind != 1:
            return False
        kind = 'RECEIVE_BLIND'
    
    # Only RECEIVE_BLIND transfers can expire
    if isinstance(kind, str) and kind.upper() == 'RECEIVE_BLIND' and expiration < now:
        return True
    
    return False


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
    
    # Create watcher entry when watcher starts
    try:
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
                    logger.info(
                        f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Transfer {recipient_id} status: {status}, kind: {kind}"
                    )
                    
                    # Check for terminal states
                    if _is_transfer_completed(transfer):
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
                    if _is_transfer_expired(transfer):
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
                            logger.info(
                                f"[TransferWatcher] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                f"Refreshed wallet for transfer {recipient_id} (count: {refresh_count})"
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

