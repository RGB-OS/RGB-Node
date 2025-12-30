"""Address and invoice management for single-use deposit addresses."""
from datetime import datetime, timedelta
from src.bitcoinl1.model import UnusedDepositAddress
from src.rln_client import get_rln_client
from src.bitcoinl1.watcher import start_watcher
from src.bitcoinl1 import tempstorage


async def get_or_create_address() -> str:
    """
    Get existing address or create a new one.
    
    Returns:
        Bitcoin address (cached or newly generated)
    """
    if tempstorage.deposit_address:
        return tempstorage.deposit_address.address
    
    # Generate new address
    rln = get_rln_client()
    btc_address = await rln.get_address()
    
    tempstorage.deposit_address = UnusedDepositAddress(
        address=btc_address,
        created_at=int(datetime.utcnow().timestamp())
    )
    
    return btc_address


async def get_or_create_asset_invoice() -> str:
    """
    Get existing invoice or create a new one.
    
    Returns:
        Asset invoice (cached or newly generated)
    """
    if tempstorage.cached_asset_invoice:
        return tempstorage.cached_asset_invoice
    
    # Generate new invoice
    rln = get_rln_client()
    
    rgb_invoice_data = await rln.create_rgb_invoice(
        min_confirmations=1,
        duration_seconds=86400,
        witness=False
    )
    asset_invoice = rgb_invoice_data.get("invoice")
    batch_transfer_idx = rgb_invoice_data.get("batch_transfer_idx")
    
    # Start background watcher for transfer status (fire-and-forget, non-blocking)
    # The watcher will handle expiration (1 hour) and cleanup
    if batch_transfer_idx is not None:
        start_watcher(batch_transfer_idx)
    
    # Cache the invoice
    tempstorage.cached_asset_invoice = asset_invoice
    tempstorage.cached_expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
    tempstorage.cached_batch_transfer_idx = batch_transfer_idx
    tempstorage.cached_invoice_created_at = int(datetime.utcnow().timestamp())
    
    return asset_invoice


def get_cached_expires_at():
    """
    Get cached expiration timestamp.
    
    Returns:
        Expiration timestamp or None if not cached
    """
    return tempstorage.cached_expires_at


def get_deposit_address():
    """
    Get cached deposit address.
    
    Returns:
        Cached deposit address or None
    """
    return tempstorage.deposit_address


def cleanup_deposit_address():
    """
    Clean up cached deposit address.
    """
    tempstorage.deposit_address = None

