"""
Unified wallet handler.

Processes all assets and transfers for a wallet, creating watchers for incomplete transfers.
"""
import logging
from typing import Dict, Any, List, Optional
from workers.config import MAX_RETRIES, RETRY_DELAY_BASE
from workers.api.client import get_api_client
from workers.processors.transfer_utils import (
    is_transfer_completed,
    is_transfer_expired,
    get_transfer_identifier,
    can_cancel_transfer,
)
from workers.utils import retry_with_backoff, format_wallet_id
from workers.models import WalletCredentials, Job
from src.queue import (
    acquire_wallet_lock,
    release_wallet_lock,
    create_watcher,
    get_watcher_status,
)

logger = logging.getLogger(__name__)


def _should_watch_transfer(transfer: Dict[str, Any]) -> bool:
    """
    Determine if a transfer should be watched.
    
    Args:
        transfer: Transfer dictionary
        
    Returns:
        True if transfer should be watched, False otherwise
    """
    if is_transfer_completed(transfer):
        return False
    
    if is_transfer_expired(transfer):
        return False
    
    return True


def _refresh_wallet_with_retry(
    credentials: WalletCredentials,
    max_retries: int,
    shutdown_flag: callable
) -> None:
    """
    Refresh wallet state with retry logic.
    
    Args:
        credentials: Wallet credentials
        max_retries: Maximum number of retry attempts
        shutdown_flag: Callable that returns True if shutdown requested
    """
    api_client = get_api_client()
    job_dict = credentials.to_dict()
    attempts = 0
    
    while attempts < max_retries and not shutdown_flag():
        try:
            wallet_id = format_wallet_id(credentials.xpub_van)
            logger.info(
                f"[UnifiedHandler] Wallet {wallet_id} - Refreshing wallet "
                f"(attempt {attempts + 1}/{max_retries})"
            )
            api_client.refresh_wallet(job_dict)
            logger.info(f"[UnifiedHandler] Wallet {wallet_id} - Refresh successful")
            return
        except Exception as e:
            attempts += 1
            if attempts >= max_retries:
                logger.error(
                    f"[UnifiedHandler] Max retries reached for {credentials.xpub_van}: {e}"
                )
                raise
            
            delay = RETRY_DELAY_BASE * (2 ** (attempts - 1))
            wallet_id = format_wallet_id(credentials.xpub_van)
            logger.warning(
                f"[UnifiedHandler] Wallet {wallet_id} - Refresh failed, "
                f"retrying in {delay}s: {e}"
            )
            import time
            time.sleep(delay)


def _create_watcher_for_transfer(
    credentials: WalletCredentials,
    recipient_id: str,
    asset_id: Optional[str]
) -> None:
    """
    Create watcher entry for a transfer if it doesn't exist.
    
    Args:
        credentials: Wallet credentials
        recipient_id: Transfer recipient ID
        asset_id: Optional asset ID
    """
    wallet_id = format_wallet_id(credentials.xpub_van)
    existing_watcher = get_watcher_status(credentials.xpub_van, recipient_id)
    
    if existing_watcher:
        logger.debug(
            f"[UnifiedHandler] Wallet {wallet_id} - "
            f"Watcher already exists for transfer {recipient_id}"
        )
        return
    
    try:
        create_watcher(
            xpub_van=credentials.xpub_van,
            xpub_col=credentials.xpub_col,
            master_fingerprint=credentials.master_fingerprint,
            recipient_id=recipient_id,
            asset_id=asset_id
        )
        logger.info(
            f"[UnifiedHandler] Wallet {wallet_id} - "
            f"Created watcher entry for transfer {recipient_id}"
        )
    except Exception as e:
        logger.error(
            f"[UnifiedHandler] Wallet {wallet_id} - "
            f"Failed to create watcher for transfer {recipient_id}: {e}"
        )


def _process_transfers_for_asset(
    credentials: WalletCredentials,
    asset_id: Optional[str],
    transfers: List[Dict[str, Any]],
    shutdown_flag: callable
) -> None:
    """
    Process transfers for a specific asset (or without asset_id) and create watchers for incomplete ones.
    
    Args:
        credentials: Wallet credentials
        asset_id: Asset ID (None for transfers without asset_id)
        transfers: List of transfer dictionaries
        shutdown_flag: Callable that returns True if shutdown requested
    """
    wallet_id = format_wallet_id(credentials.xpub_van)
    
    for transfer in transfers:
        if shutdown_flag():
            break
        
        recipient_id = get_transfer_identifier(transfer=transfer)
        
        if not recipient_id:
            logger.debug(
                f"[UnifiedHandler] Wallet {wallet_id} - "
                f"Transfer has no recipient_id, cannot create watcher"
            )
            continue
        
        if _should_watch_transfer(transfer):
            _create_watcher_for_transfer(credentials, recipient_id, asset_id)
        elif is_transfer_expired(transfer):
            if can_cancel_transfer(transfer):
                batch_transfer_idx = transfer.get('batch_transfer_idx')
                if batch_transfer_idx is not None:
                    try:
                        api_client = get_api_client()
                        job_dict = credentials.to_dict()
                        result = api_client.fail_transfers(
                            job=job_dict,
                            batch_transfer_idx=batch_transfer_idx,
                            no_asset_only=False,
                            skip_sync=False
                        )
                        logger.info(
                            f"[UnifiedHandler] Wallet {wallet_id} - "
                            f"Failed expired transfer {recipient_id} (batch_transfer_idx={batch_transfer_idx}): {result}"
                        )
                    except Exception as e:
                        logger.error(
                            f"[UnifiedHandler] Wallet {wallet_id} - "
                            f"Failed to call failtransfers for expired transfer {recipient_id}: {e}",
                            exc_info=True
                        )
                else:
                    logger.warning(
                        f"[UnifiedHandler] Wallet {wallet_id} - "
                        f"Transfer {recipient_id} expired but missing batch_transfer_idx"
                    )
            else:
                logger.debug(
                    f"[UnifiedHandler] Wallet {wallet_id} - "
                    f"Transfer {recipient_id} expired but cannot be cancelled (doesn't meet cancellation criteria)"
                )
        else:
            logger.debug(
                f"[UnifiedHandler] Wallet {wallet_id} - "
                f"Transfer {recipient_id} is completed"
            )


def _process_assets_and_transfers(
    credentials: WalletCredentials,
    shutdown_flag: callable
) -> None:
    """
    Process all assets and their transfers, creating watchers for incomplete transfers.
    
    First processes transfers without asset_id (invoices created without asset_id),
    then processes all assets and their transfers.
    
    Args:
        credentials: Wallet credentials
        shutdown_flag: Callable that returns True if shutdown requested
    """
    api_client = get_api_client()
    job_dict = credentials.to_dict()
    wallet_id = format_wallet_id(credentials.xpub_van)
    
    logger.info(f"[UnifiedHandler] Wallet {wallet_id} - Listing transfers without asset_id...")
    transfers_without_asset = api_client.list_transfers(job_dict, asset_id=None)
    logger.info(f"[UnifiedHandler] Wallet {wallet_id} - Found {len(transfers_without_asset)} transfer(s) without asset_id")
    
    if transfers_without_asset:
        _process_transfers_for_asset(credentials, None, transfers_without_asset, shutdown_flag)
    
    logger.info(f"[UnifiedHandler] Wallet {wallet_id} - Listing assets...")
    assets = api_client.list_assets(job_dict)
    logger.info(f"[UnifiedHandler] Wallet {wallet_id} - Found {len(assets)} asset(s)")
    
    for asset in assets:
        if shutdown_flag():
            break
        
        asset_id = asset.get('asset_id')
        if not asset_id:
            logger.warning(
                f"[UnifiedHandler] Wallet {wallet_id} - "
                f"Asset missing asset_id: {asset}"
            )
            continue
        
        asset_id_str = str(asset_id)
        logger.debug(
            f"[UnifiedHandler] Wallet {wallet_id} - "
            f"Listing transfers for asset {asset_id_str}"
        )
        
        transfers = api_client.list_transfers(job_dict, asset_id_str)
        logger.debug(
            f"[UnifiedHandler] Wallet {wallet_id} - "
            f"Found {len(transfers)} transfer(s) for asset {asset_id_str}"
        )
        
        _process_transfers_for_asset(credentials, asset_id_str, transfers, shutdown_flag)
    
    logger.info(
        f"[UnifiedHandler] Wallet {wallet_id} - "
        f"Completed processing all assets and transfers"
    )


def process_wallet_unified(job: Dict[str, Any], shutdown_flag: callable) -> None:
    """
    Unified wallet processing handler.
    
    Processes a wallet by:
    1. Refreshing wallet state (with retry)
    2. Listing all assets
    3. For each asset, listing transfers
    4. Creating watchers for incomplete transfers (if they don't exist)
    
    Args:
        job: Job dictionary with wallet credentials
        shutdown_flag: Callable that returns True if shutdown requested
    """
    job_obj = Job.from_dict(job)
    credentials = job_obj.get_credentials()
    max_retries = job_obj.max_retries
    
    if not acquire_wallet_lock(credentials.xpub_van):
        wallet_id = format_wallet_id(credentials.xpub_van)
        logger.warning(
            f"[UnifiedHandler] Wallet {wallet_id} is already being processed, skipping..."
        )
        return
    
    try:
        _refresh_wallet_with_retry(credentials, max_retries, shutdown_flag)
        _process_assets_and_transfers(credentials, shutdown_flag)
    finally:
        release_wallet_lock(credentials.xpub_van)
