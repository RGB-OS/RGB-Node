"""Settlement logic for opening Lightning channels."""
import os
import hashlib
import secrets
import logging
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from src.rln_client import get_rln_client
from src.bitcoinl1.address_manager import get_deposit_address, cleanup_deposit_address

logger = logging.getLogger(__name__)

# Fee reserve for channel opening (on-chain transaction fees)
# Typical channel opening needs ~500-2000 sats for fees depending on network conditions
CHANNEL_OPEN_FEE_RESERVE = 2000  # Reserve 2000 sats for fees


def generate_temporary_channel_id() -> str:
    """
    Generate a temporary channel ID (SHA256 of random 32 bytes).
    
    Returns:
        Hex string of SHA256 hash
    """
    random_bytes = secrets.token_bytes(32)
    return hashlib.sha256(random_bytes).hexdigest()


def create_btc_channel_config(
    lsp_peer: str,
    channel_capacity: int
) -> Dict[str, Any]:
    """
    Create BTC channel configuration.
    
    Args:
        lsp_peer: LSP peer pubkey and address
        channel_capacity: Channel capacity in sats
        
    Returns:
        Channel configuration dictionary
    """
    return {
        "peer_pubkey_and_opt_addr": lsp_peer,
        "capacity_sat": channel_capacity,
        "push_msat": 0,
        "public": True,
        "with_anchors": True,
        "fee_base_msat": 1000,
        "fee_proportional_millionths": 0,
        "temporary_channel_id": generate_temporary_channel_id()
    }


def create_asset_channel_config(
    lsp_peer: str,
    channel_capacity: int,
    asset_id: str,
    asset_amount: int
) -> Dict[str, Any]:
    """
    Create asset channel configuration.
    
    Args:
        lsp_peer: LSP peer pubkey and address
        channel_capacity: Channel capacity in sats
        asset_id: Asset ID
        asset_amount: Asset amount to settle
        
    Returns:
        Channel configuration dictionary
    """
    config = create_btc_channel_config(lsp_peer, channel_capacity)
    config["asset_id"] = asset_id
    config["asset_amount"] = asset_amount
    return config


async def find_deposit_transaction(rln, deposit_created_at: int) -> Optional[int]:
    """
    Find deposit transaction that occurred after address creation.
    
    Args:
        rln: RLN client instance
        deposit_created_at: Timestamp when deposit address was created
        
    Returns:
        Received amount from matching transaction, or None if not found
    """
    try:
        transactions_data = await rln.list_transactions(skip_sync=False)
        transactions = transactions_data.get("transactions", [])
        
        for tx in transactions:
            sent = tx.get("sent", 0)
            received = tx.get("received", 0)
            confirmation_time = tx.get("confirmation_time", {})
            tx_timestamp = confirmation_time.get("timestamp", 0)
            
            if sent == 0 and received > 0 and tx_timestamp > deposit_created_at:
                logger.info(
                    f"Found deposit transaction: received={received} sats, "
                    f"timestamp={tx_timestamp} (address created at {deposit_created_at})"
                )
                return received
        
        return None
    except Exception as e:
        logger.warning(f"Error finding deposit transaction: {e}")
        return None


async def get_btc_settlement_amount(rln, vanilla_spendable: int) -> Optional[int]:
    """
    Get the amount to use for BTC channel opening.
    Checks for deposit transactions if address exists.
    
    Args:
        rln: RLN client instance
        vanilla_spendable: Available vanilla balance in sats
        
    Returns:
        Amount to use for channel opening if deposit found and conditions met, None otherwise
    """
    deposit_address = get_deposit_address()
    
    if not deposit_address:
        logger.debug("No deposit address found, skipping BTC channel")
        return None
    
    deposit_created_at = deposit_address.created_at
    
    deposit_received = await find_deposit_transaction(rln, deposit_created_at)
    
    if deposit_received is None:
        logger.debug("No matching deposit transaction found, skipping BTC channel")
        return None
    
    if vanilla_spendable > deposit_received:
        logger.info(
            f"Using deposit_received={deposit_received} sats for channel "
            f"(vanilla_spendable={vanilla_spendable} sats)"
        )
        return deposit_received
    else:
        logger.debug(
            f"vanilla_spendable={vanilla_spendable} <= deposit_received={deposit_received}, "
            f"skipping BTC channel"
        )
        return None


async def open_btc_channel(
    rln,
    lsp_peer: str,
    vanilla_spendable: int
) -> Dict[str, Any]:
    """
    Open BTC channel if balance is sufficient.
    
    Args:
        rln: RLN client instance
        lsp_peer: LSP peer pubkey and address
        vanilla_spendable: Available vanilla balance in sats
        
    Returns:
        Result dictionary with type, capacity_sat, fee_reserve, and result/error
    """
    if vanilla_spendable <= CHANNEL_OPEN_FEE_RESERVE:
        if vanilla_spendable > 0:
            logger.warning(
                f"Insufficient balance to open BTC channel: {vanilla_spendable} sats available, "
                f"need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats"
            )
            return {
                "type": "btc",
                "error": f"Insufficient balance: {vanilla_spendable} sats available, need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats (including fee reserve)"
            }
        return None
    
    # Reserve fees from capacity
    channel_capacity = vanilla_spendable - CHANNEL_OPEN_FEE_RESERVE
    btc_channel_config = create_btc_channel_config(lsp_peer, channel_capacity)
    
    try:
        btc_channel_result = await rln.open_channel(btc_channel_config)
        logger.info(
            f"Opened BTC channel with capacity {channel_capacity} sats "
            f"(reserved {CHANNEL_OPEN_FEE_RESERVE} sats for fees)"
        )
        # Clean up deposit address since it was used to open channel
        cleanup_deposit_address()
        logger.info("Cleaned up deposit address after successful BTC channel opening")
        return {
            "type": "btc",
            "capacity_sat": channel_capacity,
            "fee_reserve": CHANNEL_OPEN_FEE_RESERVE,
            "result": btc_channel_result
        }
    except Exception as e:
        logger.error(f"Failed to open BTC channel: {e}")
        return {
            "type": "btc",
            "capacity_sat": channel_capacity,
            "fee_reserve": CHANNEL_OPEN_FEE_RESERVE,
            "error": str(e)
        }


async def open_asset_channels(
    rln,
    lsp_peer: str,
    assets_data: Dict[str, Any],
    vanilla_spendable: int
) -> List[Dict[str, Any]]:
    """
    Open asset channels for assets that need settlement.
    
    Args:
        rln: RLN client instance
        lsp_peer: LSP peer pubkey and address
        assets_data: Assets data from RLN node
        vanilla_spendable: Available vanilla balance in sats
        
    Returns:
        List of result dictionaries for each asset channel attempt
    """
    results = []
    nia_assets = assets_data.get("nia", [])
    
    # Get the allowed asset ID from environment
    rln_asset_id = os.getenv("RLN_ASSET_ID")
    
    for asset in nia_assets:
        balance_data = asset.get("balance", {})
        offchain_outbound = balance_data.get("offchain_outbound", 0)
        spendable = balance_data.get("spendable", 0)
        
        if offchain_outbound >= spendable:
            continue
        
        asset_id = asset.get("asset_id")
        
        if not asset_id:
            logger.warning("Skipping asset channel: missing asset_id")
            continue
        
        # Temporarily: only process assets matching RLN_ASSET_ID
        if rln_asset_id and asset_id != rln_asset_id:
            logger.debug(f"Skipping asset channel for {asset_id}: does not match RLN_ASSET_ID ({rln_asset_id})")
            continue
        
        amount_to_settle = spendable - offchain_outbound
        
        if amount_to_settle <= 0:
            logger.debug(f"Skipping asset channel for {asset_id}: no amount to settle")
            continue
        
        # Asset channels need BTC capacity to open
        if vanilla_spendable <= CHANNEL_OPEN_FEE_RESERVE:
            logger.warning(
                f"Skipping asset channel for {asset_id}: insufficient vanilla balance "
                f"for channel capacity (need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats)"
            )
            results.append({
                "type": "asset",
                "asset_id": asset_id,
                "asset_amount": amount_to_settle,
                "error": f"Insufficient vanilla balance: {vanilla_spendable} sats available, need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats (including fee reserve)"
            })
            continue
        
        # default capacity for asset channels
        asset_channel_capacity = 30010
        asset_channel_config = create_asset_channel_config(
            lsp_peer,
            asset_channel_capacity,
            asset_id,
            amount_to_settle
        )
        
        try:
            asset_channel_result = await rln.open_channel(asset_channel_config)
            logger.info(
                f"Opened asset channel for {asset_id} with amount {amount_to_settle} "
                f"(spendable: {spendable}, offchain_outbound: {offchain_outbound})"
            )
            results.append({
                "type": "asset",
                "asset_id": asset_id,
                "asset_amount": amount_to_settle,
                "result": asset_channel_result
            })
        except Exception as e:
            logger.error(f"Failed to open asset channel for {asset_id}: {e}")
            results.append({
                "type": "asset",
                "asset_id": asset_id,
                "asset_amount": amount_to_settle,
                "error": str(e)
            })
    
    return results


async def check_pending_channels(rln) -> bool:
    """
    Check if there are any channels in Opening status or not ready.
    
    Args:
        rln: RLN client instance
        
    Returns:
        True if there are pending channels, False otherwise
    """
    try:
        channels_data = await rln.list_channels()
        channels = channels_data.get("channels", [])
        
        for channel in channels:
            status = channel.get("status", "")
            ready = channel.get("ready", True)
            
            if status == "Opening" or not ready:
                logger.info(
                    f"Found pending channel: status={status}, ready={ready}, "
                    f"channel_id={channel.get('channel_id', 'unknown')}"
                )
                return True
        
        return False
    except Exception as e:
        logger.warning(f"Error checking pending channels: {e}")
        # If we can't check, allow proceeding (fail-safe)
        return False


async def settle_balances() -> Dict[str, Any]:
    """
    Settle on-chain balances by opening Lightning channels.
    
    - Opens BTC channel if vanilla balance spendable > 0
    - Opens asset channels for each asset with offchain_outbound < spendable
    
    Returns:
        Dictionary with results and total_channels_opened count
    """
    lsp_peer = os.getenv("RLN_LSP_PEER")
    if not lsp_peer:
        raise HTTPException(
            status_code=400,
            detail="RLN_LSP_PEER environment variable must be set"
        )
    
    rln = get_rln_client()
    
    # Check for pending channels before opening new ones
    has_pending_channels = await check_pending_channels(rln)
    if has_pending_channels:
        return {
            "error": "Transaction in progress, please try again later",
            "message": "There are channels currently opening or not ready. Please wait for them to complete before opening new channels.",
            "results": [],
            "total_channels_opened": 0
        }
    
    # Get current balance
    btc_balance_data = await rln.get_btc_balance()
    assets_data = await rln.list_assets(filter_asset_schemas=["Nia"])
    
    results = []
    vanilla_spendable = btc_balance_data.get("vanilla", {}).get("spendable", 0)
    
    btc_settlement_amount = await get_btc_settlement_amount(rln, vanilla_spendable)
    
    if btc_settlement_amount is not None:
        btc_result = await open_btc_channel(rln, lsp_peer, btc_settlement_amount)
        if btc_result:
            results.append(btc_result)
    
    # Open asset channels
    asset_results = await open_asset_channels(rln, lsp_peer, assets_data, vanilla_spendable)
    results.extend(asset_results)
    
    return {
        "results": results,
        "total_channels_opened": len([r for r in results if "error" not in r])
    }

