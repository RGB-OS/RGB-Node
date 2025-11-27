"""
Unified wallet handler.

Processes all assets and transfers for a wallet, creating watchers for incomplete transfers.
One job per wallet - handles everything in a single pass.
"""
import time
import logging
from typing import Dict, Any, List, Optional
from workers.config import MAX_RETRIES, RETRY_DELAY_BASE, REFRESH_INTERVAL
from workers.api.client import get_api_client
from src.queue import (
    acquire_wallet_lock,
    release_wallet_lock,
    create_watcher,
    get_watcher_status,
)

logger = logging.getLogger(__name__)


def _is_transfer_completed(transfer: Dict[str, Any]) -> bool:
    """
    Check if a transfer is in a terminal state.
    
    Args:
        transfer: Transfer dictionary
        
    Returns:
        True if transfer is completed (settled or failed), False otherwise
    """
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
    """
    Check if a transfer has expired.
    
    Args:
        transfer: Transfer dictionary
        
    Returns:
        True if transfer is expired, False otherwise
    """
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


def _get_transfer_identifier(transfer: Dict[str, Any]) -> Optional[str]:
    """
    Get a unique identifier for a transfer to use as watcher key.
    
    Uses recipient_id (required for watchers).
    
    Args:
        transfer: Transfer dictionary
        
    Returns:
        recipient_id if available, None otherwise
    """
    return transfer.get('recipient_id')


def _should_watch_transfer(transfer: Dict[str, Any]) -> bool:
    """
    Determine if a transfer should be watched.
    
    Args:
        transfer: Transfer dictionary
        
    Returns:
        True if transfer should be watched, False otherwise
    """
    # Don't watch completed transfers
    if _is_transfer_completed(transfer):
        return False
    
    # Don't watch expired transfers (they will be handled separately)
    if _is_transfer_expired(transfer):
        return False
    
    # Watch all non-terminal transfers
    return True


# Note: Watchers are not created in unified flow - they should be created separately when needed


def process_wallet_unified(job: Dict[str, Any], shutdown_flag: callable) -> None:
    """
    Unified wallet processing handler.
    
    Processes a wallet by:
    1. Refreshing wallet state
    2. Listing all assets
    3. For each asset, listing transfers
    4. Creating watchers for incomplete transfers (if they don't exist)
    
    This ensures one job per wallet handles everything.
    
    Args:
        job: Job dictionary with wallet credentials
        shutdown_flag: Callable that returns True if shutdown requested
    """
    xpub_van = job['xpub_van']
    max_retries = job.get('max_retries', MAX_RETRIES)
    attempts = 0
    
    # Acquire wallet lock - ensures only one job per wallet processes at a time
    if not acquire_wallet_lock(xpub_van):
        logger.warning(
            f"[UnifiedHandler] Wallet {xpub_van} is already being processed, skipping..."
        )
        return
    
    api_client = get_api_client()
    
    try:
        # Retry logic for wallet refresh
        while attempts < max_retries and not shutdown_flag():
            try:
                logger.info(
                    f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Refreshing wallet "
                    f"(attempt {attempts + 1}/{max_retries})"
                )
                api_client.refresh_wallet(job)
                logger.info(f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Refresh successful")
                
                # After successful refresh, process all assets and transfers
                logger.info(
                    f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Listing assets..."
                )
                assets = api_client.list_assets(job)
                logger.info(
                    f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Found {len(assets)} asset(s)"
                )
                
                # Process each asset
                for asset in assets:
                    if shutdown_flag():
                        break
                    
                    # Asset can be AssetModel with asset_id field
                    asset_id = asset.get('asset_id')
                    if not asset_id:
                        logger.warning(
                            f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                            f"Asset missing asset_id: {asset}"
                        )
                        continue
                    
                    # Store asset_id in transfer context for later use
                    asset_id_str = str(asset_id)
                    
                    logger.debug(
                        f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Listing transfers for asset {asset_id_str}"
                    )
                    
                    # Get transfers for this asset
                    transfers = api_client.list_transfers(job, asset_id_str)
                    logger.debug(
                        f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Found {len(transfers)} transfer(s) for asset {asset_id_str}"
                    )
                    
                    # Process each transfer
                    for transfer in transfers:
                        if shutdown_flag():
                            break
                        
                        transfer_status = transfer.get('status')
                        transfer_kind = transfer.get('kind')
                        recipient_id = transfer.get('recipient_id')
                        
                        logger.debug(
                            f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                            f"Transfer recipient_id={recipient_id}, "
                            f"status={transfer_status}, kind={transfer_kind}"
                        )
                        
                        # Check if transfer should be watched
                        if _should_watch_transfer(transfer):
                            transfer_id = _get_transfer_identifier(transfer)
                            if transfer_id:
                                # Check if watcher already exists
                                existing_watcher = get_watcher_status(xpub_van, transfer_id)
                                if existing_watcher:
                                    logger.debug(
                                        f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                        f"Watcher already exists for transfer {transfer_id}"
                                    )
                                else:
                                    # Create watcher entry (will be processed by wallet worker)
                                    try:
                                        create_watcher(
                                            xpub_van=xpub_van,
                                            xpub_col=job['xpub_col'],
                                            master_fingerprint=job['master_fingerprint'],
                                            recipient_id=transfer_id,
                                            asset_id=asset_id
                                        )
                                        logger.info(
                                            f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                            f"Created watcher entry for transfer {transfer_id}"
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                            f"Failed to create watcher for transfer {transfer_id}: {e}"
                                        )
                            else:
                                logger.debug(
                                    f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                    f"Transfer has no recipient_id, cannot create watcher"
                                )
                        elif _is_transfer_expired(transfer):
                            logger.debug(
                                f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                f"Transfer recipient_id={recipient_id} is expired"
                            )
                            # TODO: Handle expired transfers (mark as failed, cleanup, etc.)
                        else:
                            logger.debug(
                                f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                                f"Transfer recipient_id={recipient_id} is completed "
                                f"(status={transfer_status})"
                            )
                
                logger.info(
                    f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                    f"Completed processing all assets and transfers"
                )
                return
                
            except Exception as e:
                attempts += 1
                if attempts >= max_retries:
                    logger.error(
                        f"[UnifiedHandler] Max retries reached for {xpub_van}: {e}"
                    )
                    break
                
                delay = RETRY_DELAY_BASE * (2 ** (attempts - 1))
                logger.warning(
                    f"[UnifiedHandler] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Refresh failed, "
                    f"retrying in {delay}s: {e}"
                )
                time.sleep(delay)
        
    finally:
        release_wallet_lock(xpub_van)

