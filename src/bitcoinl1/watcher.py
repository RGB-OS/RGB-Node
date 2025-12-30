"""Transfer status watcher for background monitoring."""
from datetime import datetime, timedelta
import asyncio
import logging
import os
from src.rln_client import get_rln_client

logger = logging.getLogger(__name__)

# Storage for active watchers
active_watchers: dict[int, asyncio.Task] = {}


def cleanup_cached_invoice():
    """
    Clean up cached invoice from tempstorage.
    """
    try:
        from src.bitcoinl1 import tempstorage
        tempstorage.cached_asset_invoice = None
        tempstorage.cached_expires_at = None
        tempstorage.cached_batch_transfer_idx = None
        tempstorage.cached_invoice_created_at = None
        logger.info("Cleaned up cached invoice")
    except Exception as e:
        logger.warning(f"Error cleaning up cached invoice: {e}")


async def watch_transfer_status(batch_transfer_idx: int):
    """
    Background watcher that polls transfer status every 40 seconds.
    Stops when transfer status is 'Settled' or 'Failed', or after 1 hour max.
    Fails transfers if 1 hour exceeded and cleans up cached invoice.
    
    Args:
        batch_transfer_idx: The transfer index to watch
    """
    asset_id = os.getenv("RLN_ASSET_ID")
    if not asset_id:
        logger.error("RLN_ASSET_ID environment variable must be set for transfer watcher")
        return
    
    rln = get_rln_client()
    start_time = datetime.utcnow()
    max_duration = timedelta(hours=1)
    poll_interval = 40  # seconds
    
    logger.info(f"Starting watcher for transfer idx={batch_transfer_idx}")
    
    try:
        while True:
            # Check if max time exceeded (1 hour)
            elapsed = datetime.utcnow() - start_time
            if elapsed >= max_duration:
                logger.info(f"Watcher for transfer idx={batch_transfer_idx} stopped: max duration (1 hour) exceeded")
                # Fail the transfers since 1 hour has passed
                try:
                    await rln.fail_transfers(
                        batch_transfer_idx=batch_transfer_idx,
                        no_asset_only=False,
                        skip_sync=False
                    )
                    logger.info(f"Failed transfers for idx={batch_transfer_idx} after 1 hour expiration")
                except Exception as e:
                    logger.error(f"Error failing transfers for idx={batch_transfer_idx}: {e}")
                # Clean up cached invoice
                cleanup_cached_invoice()
                break
            
            # Refresh transfers
            try:
                await rln.refresh_transfers(skip_sync=False)
            except Exception as e:
                logger.warning(f"Error refreshing transfers for idx={batch_transfer_idx}: {e}")
            
            # Get transfers and check status
            try:
                transfers_data = await rln.list_transfers(asset_id)
                transfers = transfers_data.get("transfers", [])
                
                # Find transfer with matching idx
                target_transfer = None
                for transfer in transfers:
                    if transfer.get("idx") == batch_transfer_idx:
                        target_transfer = transfer
                        break
                
                if target_transfer:
                    status = target_transfer.get("status")
                    logger.debug(f"Transfer idx={batch_transfer_idx} status: {status}")
                    
                    if status in ["Settled", "Failed"]:
                        logger.info(f"Watcher for transfer idx={batch_transfer_idx} stopped: status={status}")
                        # Clean up cached invoice when settled or failed
                        cleanup_cached_invoice()
                        break
                else:
                    logger.debug(f"Transfer idx={batch_transfer_idx} not found in transfers list")
            
            except Exception as e:
                logger.warning(f"Error checking transfer status for idx={batch_transfer_idx}: {e}")
            
            # Wait before next poll
            await asyncio.sleep(poll_interval)
    
    except asyncio.CancelledError:
        logger.info(f"Watcher for transfer idx={batch_transfer_idx} was cancelled")
    except Exception as e:
        logger.error(f"Watcher for transfer idx={batch_transfer_idx} encountered error: {e}")
    finally:
        # Clean up watcher from active_watchers
        if batch_transfer_idx in active_watchers:
            del active_watchers[batch_transfer_idx]
        logger.info(f"Watcher for transfer idx={batch_transfer_idx} cleaned up")


def start_watcher(batch_transfer_idx: int) -> bool:
    """
    Start a background watcher for a transfer if it doesn't already exist.
    
    Args:
        batch_transfer_idx: The transfer index to watch
        
    Returns:
        bool: True if watcher was started, False if it already exists
    """
    if batch_transfer_idx not in active_watchers:
        watcher_task = asyncio.create_task(watch_transfer_status(batch_transfer_idx))
        active_watchers[batch_transfer_idx] = watcher_task
        logger.info(f"Started background watcher for transfer idx={batch_transfer_idx}")
        return True
    else:
        logger.warning(f"Watcher for transfer idx={batch_transfer_idx} already exists")
        return False

