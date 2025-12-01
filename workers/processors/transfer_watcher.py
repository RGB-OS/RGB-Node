"""
Unified transfer watcher.

Watches transfers until they're settled, failed, or expired.
Refactored into classes for better structure and maintainability.
"""
import time
import logging
from typing import Optional, Dict, Any
from workers.config import REFRESH_INTERVAL, WALLET_LOCK_TTL
from workers.api.client import get_api_client
from workers.processors.transfer_utils import is_transfer_completed, is_transfer_expired, can_cancel_transfer
from workers.utils import format_wallet_id, normalize_transfer_status
from workers.models import WalletCredentials, Watcher
from src.queue import (
    create_watcher,
    update_watcher_status,
    update_watcher_asset_and_expiration,
    stop_watcher,
    get_watcher_status,
    acquire_wallet_lock,
    release_wallet_lock,
    enqueue_refresh_job,
)

logger = logging.getLogger(__name__)


class WatcherLifecycle:
    """Manages watcher lifecycle (creation, updates, stopping)."""
    
    def __init__(self, credentials: WalletCredentials, recipient_id: str, asset_id: Optional[str]):
        """
        Initialize watcher lifecycle manager.
        
        Args:
            credentials: Wallet credentials
            recipient_id: Transfer recipient ID
            asset_id: Optional asset ID
        """
        self.credentials = credentials
        self.recipient_id = recipient_id
        self.asset_id = asset_id
        self.wallet_id = format_wallet_id(credentials.xpub_van)
    
    def ensure_watcher_exists(self) -> None:
        """Ensure watcher entry exists in database."""
        existing_watcher = get_watcher_status(self.credentials.xpub_van, self.recipient_id)
        
        if existing_watcher:
            logger.debug(
                f"[TransferWatcher] Wallet {self.wallet_id} - Watcher already exists "
                f"for transfer {self.recipient_id}, preserving expiration"
            )
            return
        
        try:
            create_watcher(
                xpub_van=self.credentials.xpub_van,
                xpub_col=self.credentials.xpub_col,
                master_fingerprint=self.credentials.master_fingerprint,
                recipient_id=self.recipient_id,
                asset_id=self.asset_id
            )
            logger.info(
                f"[TransferWatcher] Wallet {self.wallet_id} - Created watcher entry "
                f"for transfer {self.recipient_id}"
            )
        except Exception as e:
            logger.warning(
                f"[TransferWatcher] Wallet {self.wallet_id} - "
                f"Failed to create watcher entry: {e}"
            )
    
    def update_status(self, status: str, refresh_count: int) -> None:
        """Update watcher status in database."""
        update_watcher_status(
            self.credentials.xpub_van,
            self.recipient_id,
            status,
            refresh_count
        )
    
    def stop(self) -> None:
        """Stop watcher (mark as stopped in database)."""
        stop_watcher(self.credentials.xpub_van, self.recipient_id)


class TransferMonitor:
    """Monitors transfer status until completion or expiration."""
    
    def __init__(self, credentials: WalletCredentials, recipient_id: str, asset_id: Optional[str]):
        """
        Initialize transfer monitor.
        
        Args:
            credentials: Wallet credentials
            recipient_id: Transfer recipient ID
            asset_id: Optional asset ID
        """
        self.credentials = credentials
        self.recipient_id = recipient_id
        self.asset_id = asset_id
        self.wallet_id = format_wallet_id(credentials.xpub_van)
        self.api_client = get_api_client()
    
    def get_transfer_status(self) -> Optional[dict]:
        """
        Get current transfer status from API.
        
        Returns:
            Transfer dictionary or None if not found
        """
        job_dict = self.credentials.to_dict()
        job_dict['recipient_id'] = self.recipient_id
        if self.asset_id:
            job_dict['asset_id'] = self.asset_id
        
        return self.api_client.get_transfer_status(job_dict)
    
    def check_completion(self, transfer: dict) -> Optional[str]:
        """
        Check if transfer is completed.
        
        Args:
            transfer: Transfer dictionary
        
        Returns:
            Final status string if completed ('settled' or 'failed'), None otherwise
        """
        if not is_transfer_completed(transfer):
            return None
        
        status = transfer.get('status')
        return normalize_transfer_status(status)
    
    def check_expiration(self, transfer: dict) -> bool:
        """
        Check if transfer has expired.
        
        Args:
            transfer: Transfer dictionary
        
        Returns:
            True if expired, False otherwise
        """
        return is_transfer_expired(transfer)
    
    def find_transfer_in_all_assets(self) -> Optional[tuple]:
        """
        Search for transfer across all assets when asset_id is None.
        
        This is used when a transfer was created without asset_id but may have
        been assigned an asset_id after refresh.
        
        Returns:
            Tuple of (transfer_dict, asset_id) if found, None otherwise
            Note: asset_id can be None if transfer is found in list_transfers without asset_id
        """
        try:
            job_dict = self.credentials.to_dict()
            
            # First, try listing transfers without asset_id
            transfers = self.api_client.list_transfers(job_dict, asset_id=None)
            for transfer in transfers:
                if transfer.get('recipient_id') == self.recipient_id:
                    # Found in transfers without asset_id, return with asset_id=None
                    return (transfer, None)
            
            # If not found, search through all assets
            assets = self.api_client.list_assets(job_dict)
            for asset in assets:
                asset_id = asset.get('asset_id')
                if not asset_id:
                    continue
                
                asset_id_str = str(asset_id)
                asset_transfers = self.api_client.list_transfers(job_dict, asset_id_str)
                for transfer in asset_transfers:
                    if transfer.get('recipient_id') == self.recipient_id:
                        # Found in this asset, return with the asset_id
                        return (transfer, asset_id_str)
            
            return None
        except Exception as e:
            logger.warning(
                f"[TransferMonitor] Wallet {self.wallet_id} - "
                f"Error searching for transfer {self.recipient_id} across assets: {e}"
            )
            return None


class WalletRefresher:
    """Handles periodic wallet refreshes during transfer watching."""
    
    def __init__(self, credentials: WalletCredentials):
        """
        Initialize wallet refresher.
        
        Args:
            credentials: Wallet credentials
        """
        self.credentials = credentials
        self.wallet_id = format_wallet_id(credentials.xpub_van)
        self.api_client = get_api_client()
    
    def refresh(self) -> Optional[Dict[str, Any]]:
        """
        Refresh wallet state (with lock to prevent concurrent refreshes).
        
        Returns:
            Refresh response dictionary if refresh succeeded, None otherwise
        """
        if not acquire_wallet_lock(self.credentials.xpub_van, ttl=WALLET_LOCK_TTL):
            logger.debug(
                f"[TransferWatcher] Wallet {self.wallet_id} - "
                f"Wallet is being refreshed by another worker, skipping this cycle"
            )
            return None
        
        try:
            job_dict = self.credentials.to_dict()
            refresh_response = self.api_client.refresh_wallet(job_dict)
            return refresh_response
        except Exception as e:
            logger.warning(
                f"[TransferWatcher] Wallet {self.wallet_id} - "
                f"Refresh failed: {e}"
            )
            return None
        finally:
            release_wallet_lock(self.credentials.xpub_van)


class ExpirationChecker:
    """Checks watcher expiration (for invoice_created without asset_id)."""
    
    def __init__(self, credentials: WalletCredentials, recipient_id: str):
        """
        Initialize expiration checker.
        
        Args:
            credentials: Wallet credentials
            recipient_id: Transfer recipient ID
        """
        self.credentials = credentials
        self.recipient_id = recipient_id
        self.wallet_id = format_wallet_id(credentials.xpub_van)
    
    def check_and_handle_expiration(self) -> bool:
        """
        Check if watcher has expired and handle it.
        
        Returns:
            True if watcher expired and was handled, False otherwise
        """
        watcher = get_watcher_status(self.credentials.xpub_van, self.recipient_id)
        if not watcher:
            return False
        
        expires_at = watcher.get('expires_at')
        if not expires_at or not isinstance(expires_at, int):
            return False
        
        current_time = int(time.time())
        if current_time < expires_at:
            time_until_expiry = expires_at - current_time
            logger.info(
                f"[TransferWatcher] Wallet {self.wallet_id} - "
                f"Watcher expires in {time_until_expiry} seconds"
            )
            return False
        
        logger.info(
            f"[TransferWatcher] Wallet {self.wallet_id} - "
            f"Watcher for {self.recipient_id} expired (3 min), triggering sync job"
        )
        
        try:
            enqueue_refresh_job(
                xpub_van=self.credentials.xpub_van,
                xpub_col=self.credentials.xpub_col,
                master_fingerprint=self.credentials.master_fingerprint,
                trigger="sync"
            )
            logger.info(
                f"[TransferWatcher] Wallet {self.wallet_id} - "
                f"Triggered sync job after watcher expiration"
            )
        except Exception as e:
            logger.error(
                f"[TransferWatcher] Failed to trigger sync job: {e}", exc_info=True
            )
        
        return True


def watch_transfer(
    job: dict,
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
    credentials = WalletCredentials.from_dict(job)
    wallet_id = format_wallet_id(credentials.xpub_van)
    
    lifecycle = WatcherLifecycle(credentials, recipient_id, asset_id)
    monitor = TransferMonitor(credentials, recipient_id, asset_id)
    refresher = WalletRefresher(credentials)
    
    lifecycle.ensure_watcher_exists()
    
    logger.info(
        f"[TransferWatcher] Wallet {wallet_id} - Started watching "
        f"transfer {recipient_id}, asset_id={asset_id}"
    )
    
    refresh_count = 0
    
    try:
        while not shutdown_flag():
            try:
                # Removed special handling for watchers without asset_id
                # All watchers now follow the same flow - they will be processed
                # by process_wallet_unified which calls list_transfers without asset_id
                
                transfer = monitor.get_transfer_status()
                
                if not transfer:
                    # If asset_id is None and transfer not found, search across all assets
                    # The transfer might have been assigned an asset_id after creation
                    if not asset_id:
                        logger.info(
                            f"[TransferWatcher] Wallet {wallet_id} - "
                            f"Transfer {recipient_id} not found without asset_id, "
                            f"searching across all assets..."
                        )
                        result = monitor.find_transfer_in_all_assets()
                        
                        if result:
                            # Found transfer, result is (transfer_dict, asset_id)
                            transfer, found_asset_id = result
                            found_expiration = transfer.get('expiration')
                            
                            if found_asset_id:
                                logger.info(
                                    f"[TransferWatcher] Wallet {wallet_id} - "
                                    f"Found transfer {recipient_id} with asset_id={found_asset_id}, "
                                    f"updating watcher..."
                                )
                                
                                # Update watcher with asset_id and expiration
                                update_watcher_asset_and_expiration(
                                    credentials.xpub_van,
                                    recipient_id,
                                    found_asset_id,
                                    found_expiration
                                )
                                
                                monitor.asset_id = found_asset_id
                                lifecycle.asset_id = found_asset_id
                                asset_id = found_asset_id
                            else:
                                logger.info(
                                    f"[TransferWatcher] Wallet {wallet_id} - "
                                    f"Found transfer {recipient_id} but still without asset_id"
                                )
                        else:
                            logger.info(
                                f"[TransferWatcher] Wallet {wallet_id} - "
                                f"Transfer {recipient_id} not found in any asset, continuing..."
                            )
                    else:
                        logger.info(
                            f"[TransferWatcher] Wallet {wallet_id} - "
                            f"Transfer not found for {recipient_id} with asset_id={asset_id}, continuing..."
                        )
                
                if transfer:
                    final_status = monitor.check_completion(transfer)
                    if final_status:
                        lifecycle.update_status(final_status, refresh_count)
                        lifecycle.stop()
                        logger.info(
                            f"[TransferWatcher] Wallet {wallet_id} - "
                            f"Stopped watching transfer {recipient_id} - status: {final_status}"
                        )
                        return
                    
                    if monitor.check_expiration(transfer):
                        # Check if transfer can be cancelled before calling failtransfers
                        logger.info(
                            f"[TransferWatcher] Wallet {wallet_id} - "
                            f"Transfer {recipient_id} expired. Checking if can be cancelled. "
                            f"Status: {transfer.get('status')}, Kind: {transfer.get('kind')}, "
                            f"Expiration: {transfer.get('expiration')}, batch_transfer_idx: {transfer.get('batch_transfer_idx')}"
                        )
                        
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
                                        f"[TransferWatcher] Wallet {wallet_id} - "
                                        f"Failed expired transfer {recipient_id} (batch_transfer_idx={batch_transfer_idx}): {result}"
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"[TransferWatcher] Wallet {wallet_id} - "
                                        f"Failed to call failtransfers for expired transfer {recipient_id}: {e}",
                                        exc_info=True
                                    )
                            else:
                                logger.warning(
                                    f"[TransferWatcher] Wallet {wallet_id} - "
                                    f"Transfer {recipient_id} expired but missing batch_transfer_idx"
                                )
                        else:
                            logger.info(
                                f"[TransferWatcher] Wallet {wallet_id} - "
                                f"Transfer {recipient_id} expired but cannot be cancelled (doesn't meet cancellation criteria: "
                                f"status={transfer.get('status')}, kind={transfer.get('kind')}, expiration={transfer.get('expiration')})"
                            )
                        
                        lifecycle.update_status('expired', refresh_count)
                        lifecycle.stop()
                        logger.info(
                            f"[TransferWatcher] Wallet {wallet_id} - "
                            f"Stopped watching transfer {recipient_id} - expired"
                        )
                        return
                
                refresh_response = refresher.refresh()
                if refresh_response:
                    refresh_count += 1
                    
                    # Check for failures in refresh response
                    if transfer:
                        batch_transfer_idx = transfer.get('batch_transfer_idx')
                        if batch_transfer_idx is not None:
                            batch_idx_str = str(batch_transfer_idx)
                            if batch_idx_str in refresh_response:
                                transfer_result = refresh_response[batch_idx_str]
                                failure = transfer_result.get('failure')
                                if failure and failure.get('details'):
                                    failure_details = failure['details']
                                    logger.error(
                                        f"[TransferWatcher] Wallet {wallet_id} - "
                                        f"Transfer {recipient_id} (batch_transfer_idx={batch_transfer_idx}) "
                                        f"failed: {failure_details}"
                                    )
                                    lifecycle.update_status('failed', refresh_count)
                                    lifecycle.stop()
                                    logger.info(
                                        f"[TransferWatcher] Wallet {wallet_id} - "
                                        f"Stopped watching transfer {recipient_id} - refresh failure detected"
                                    )
                                    return
                    
                    lifecycle.update_status("watching", refresh_count)
                
                time.sleep(REFRESH_INTERVAL)
                
            except Exception as e:
                logger.error(
                    f"[TransferWatcher] Wallet {wallet_id} - "
                    f"Error watching transfer {recipient_id}: {e}", exc_info=True
                )
                time.sleep(REFRESH_INTERVAL)
    finally:
        if shutdown_flag():
            logger.info(
                f"[TransferWatcher] Wallet {wallet_id} - "
                f"Shutting down watcher for transfer {recipient_id}"
            )
