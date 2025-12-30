"""Withdrawal logic for BTC and asset withdrawals."""
import logging
from fastapi import HTTPException
from src.rln_client import get_rln_client
from src.lightning.model import LightningAsset

logger = logging.getLogger(__name__)


async def withdraw_asset(
    rgb_invoice: str,
    asset: LightningAsset,
    fee_rate: int
) -> tuple[str, int | None]:
    """
    Withdraw asset using RGB invoice.
    
    Args:
        rgb_invoice: RGB invoice string (starts with "rgb:")
        asset: Asset details with asset_id and amount
        fee_rate: Fee rate for the transaction
        
    Returns:
        str: Transaction ID (txid)
        
    Raises:
        HTTPException: If the request fails or required fields are missing
    """
    rln = get_rln_client()
    
    decoded_invoice = await rln.decode_rgb_invoice(rgb_invoice)
    
    recipient_id = decoded_invoice.get("recipient_id")
    transport_endpoints = decoded_invoice.get("transport_endpoints", [])
    
    if not recipient_id:
        raise HTTPException(
            status_code=400,
            detail="Decoded RGB invoice missing recipient_id"
        )
    
    asset_id = asset.asset_id
    assignment = {
        "type": "Fungible",
        "value": asset.amount
    }
    
    txid = await rln.send_asset(
        asset_id=asset_id,
        assignment=assignment,
        recipient_id=recipient_id,
        witness_data=None,
        donation=False,
        fee_rate=fee_rate,
        min_confirmations=1,
        transport_endpoints=transport_endpoints,
        skip_sync=False
    )
    
    batch_transfer_idx = None
    try:
        transfers_data = await rln.list_transfers(asset_id)
        transfers = transfers_data.get("transfers", [])
        for transfer in transfers:
            if transfer.get("txid") == txid:
                batch_transfer_idx = transfer.get("idx")
                break
        
        if batch_transfer_idx is None:
            logger.warning(
                f"Could not find batch_transfer_idx for txid={txid} in transfers list. "
                f"Continuing without watcher."
            )
    except Exception as e:
        logger.warning(
            f"Error finding batch_transfer_idx for txid={txid}: {e}. "
            f"Continuing without watcher."
        )
    
    return txid, batch_transfer_idx


async def withdraw_btc(
    address: str,
    amount_sats: int,
    fee_rate: int
) -> str:
    """
    Withdraw BTC to a Bitcoin address.
    
    Args:
        address: Bitcoin address to send to
        amount_sats: Amount in satoshis
        fee_rate: Fee rate for the transaction
        
    Returns:
        str: Transaction ID (txid)
        
    Raises:
        HTTPException: If the request fails
    """
    rln = get_rln_client()
    
    txid = await rln.send_btc(
        address=address,
        amount=amount_sats,
        fee_rate=fee_rate,
        skip_sync=False
    )
    
    return txid

