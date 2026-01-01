"""Withdrawal orchestrator for managing withdrawal flow."""
import logging
import asyncio
from datetime import datetime
from typing import Optional
from src.rln_client import get_rln_client
from src.bitcoinl1.model import (
    WithdrawalState,
    WithdrawalStatus,
    WithdrawRequestModel
)
from src.bitcoinl1.withdrawal_storage import (
    get_withdrawal,
    get_withdrawal_by_idempotency_key,
    save_withdrawal,
    update_withdrawal_status
)

logger = logging.getLogger(__name__)


async def _retry_balance_check(withdrawal_id: str, delay_seconds: int) -> None:
    """
    Retry balance check after a delay.
    
    Args:
        withdrawal_id: Withdrawal ID to retry
        delay_seconds: Delay in seconds before retrying
    """
    await asyncio.sleep(delay_seconds)
    await process_withdrawal(withdrawal_id)


async def find_channels_to_close(asset_id: Optional[str] = None) -> list[dict]:
    """
    Find channels that need to be closed.
    For BTC withdrawal, asset_id should be None.
    
    Args:
        asset_id: Asset ID to filter by (None for BTC channels)
        
    Returns:
        List of channel dictionaries to close
    """
    rln = get_rln_client()
    channels_data = await rln.list_channels()
    channels = channels_data.get("channels", [])
    
    channels_to_close = []
    for channel in channels:
        # For BTC withdrawal, asset_id should be null
        channel_asset_id = channel.get("asset_id")
        if asset_id is None and channel_asset_id is None:
            # BTC channel
            outbound_msat = channel.get("outbound_balance_msat", 0)
            if outbound_msat > 0:
                channels_to_close.append(channel)
        elif asset_id and channel_asset_id == asset_id:
            # Asset channel matching the asset_id
            asset_outbound = channel.get("asset_outbound_amount", 0)
            if asset_outbound > 0:
                channels_to_close.append(channel)
    
    return channels_to_close


async def process_withdrawal(withdrawal_id: str) -> None:
    """
    Process a withdrawal through its state machine.
    
    Args:
        withdrawal_id: Withdrawal ID to process
    """
    logger.info(f"Processing withdrawal {withdrawal_id}")
    withdrawal = get_withdrawal(withdrawal_id)
    if not withdrawal:
        logger.error(f"Withdrawal {withdrawal_id} not found")
        return
    
    logger.info(f"Withdrawal {withdrawal_id}: status={withdrawal.status}, address_or_rgbinvoice={withdrawal.address_or_rgbinvoice}, amount={withdrawal.amount_sats_requested}")
    
    rln = get_rln_client()
    
    try:
        # For now, only handle channels_only case
        if withdrawal.source not in ["channels_only", "auto"]:
            logger.warning(f"Withdrawal {withdrawal_id}: Unsupported source '{withdrawal.source}'")
            update_withdrawal_status(
                withdrawal_id,
                WithdrawalStatus.FAILED,
                error_code="UNSUPPORTED_SOURCE",
                error_message=f"Source '{withdrawal.source}' not yet supported. Only 'channels_only' and 'auto' are supported.",
                retryable=False
            )
            return
        
        if withdrawal.status == WithdrawalStatus.REQUESTED:
            logger.info(f"Withdrawal {withdrawal_id}: Finding channels to close (BTC channels)")
            
            # Get baseline balance before closing channels
            btc_balance_data = await rln.get_btc_balance()
            baseline_balance = btc_balance_data["vanilla"]["spendable"]
            logger.info(f"Withdrawal {withdrawal_id}: Baseline balance before closing: {baseline_balance} sats")
            withdrawal.baseline_balance_sats = baseline_balance
            save_withdrawal(withdrawal)
            
            # Find channels to close (for BTC withdrawal, asset_id is None)
            channels_to_close = await find_channels_to_close(asset_id=None)
            logger.info(f"Withdrawal {withdrawal_id}: Found {len(channels_to_close)} channels to close")
            
            if not channels_to_close:
                logger.info(f"Withdrawal {withdrawal_id}: No channels to close, moving to sweeping")
                # No channels to close, move to sweeping
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.SWEEPING_OUTPUTS
                )
                # Continue processing
                withdrawal = get_withdrawal(withdrawal_id)
            else:
                # Store channel IDs to close
                channel_ids = [ch.get("channel_id") for ch in channels_to_close]
                logger.info(f"Withdrawal {withdrawal_id}: Storing {len(channel_ids)} channel IDs to close: {channel_ids}")
                withdrawal.channel_ids_to_close = channel_ids
                save_withdrawal(withdrawal)
                
                logger.info(f"Withdrawal {withdrawal_id}: Updating status to CLOSING_CHANNELS")
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.CLOSING_CHANNELS
                )
                # Continue processing
                withdrawal = get_withdrawal(withdrawal_id)
        
        if withdrawal.status == WithdrawalStatus.CLOSING_CHANNELS:
            logger.info(f"Withdrawal {withdrawal_id}: Closing {len(withdrawal.channel_ids_to_close)} channels")
            # Close channels
            close_txids = []
            for idx, channel_id in enumerate(withdrawal.channel_ids_to_close, 1):
                try:
                    logger.info(f"Withdrawal {withdrawal_id}: Closing channel {idx}/{len(withdrawal.channel_ids_to_close)}: {channel_id}")
                    # Get peer_pubkey from channel data
                    channels_data = await rln.list_channels()
                    channels = channels_data.get("channels", [])
                    peer_pubkey = None
                    
                    for ch in channels:
                        if ch.get("channel_id") == channel_id:
                            peer_pubkey = ch.get("peer_pubkey")
                            break
                    
                    if not peer_pubkey:
                        logger.warning(f"Withdrawal {withdrawal_id}: Could not find peer_pubkey for channel {channel_id}")
                        continue
                    
                    # Close channel
                    force = withdrawal.close_mode == "force"
                    logger.info(f"Withdrawal {withdrawal_id}: Closing channel {channel_id} (force={force})")
                    await rln.close_channel(
                        channel_id=channel_id,
                        peer_pubkey=peer_pubkey,
                        force=False
                    )
                    logger.info(f"Withdrawal {withdrawal_id}: Channel {channel_id} close request sent successfully")
                    
                    # Refresh to confirm
                    logger.info(f"Withdrawal {withdrawal_id}: Refreshing transfers to confirm channel close")
                    await rln.refresh_transfers(skip_sync=False)
                    logger.info(f"Withdrawal {withdrawal_id}: Transfers refreshed")
                    
                    # For now, we'll track the channel_id as the close_txid
                    # In production, you'd get the actual close transaction ID
                    close_txids.append(channel_id)
                    logger.info(f"Withdrawal {withdrawal_id}: Channel {channel_id} added to close_txids")
                    
                except Exception as e:
                    logger.error(f"Withdrawal {withdrawal_id}: Error closing channel {channel_id}: {e}")
                    update_withdrawal_status(
                        withdrawal_id,
                        WithdrawalStatus.FAILED,
                        error_code="CHANNEL_CLOSE_FAILED",
                        error_message=str(e),
                        retryable=True
                    )
                    return
            
            logger.info(f"Withdrawal {withdrawal_id}: Successfully closed {len(close_txids)} channels")
            withdrawal.close_txids = close_txids
            save_withdrawal(withdrawal)
            
            logger.info(f"Withdrawal {withdrawal_id}: Updating status to WAITING_CLOSE_CONFIRMATIONS")
            update_withdrawal_status(
                withdrawal_id,
                WithdrawalStatus.WAITING_CLOSE_CONFIRMATIONS
            )
            withdrawal = get_withdrawal(withdrawal_id)
        
        if withdrawal.status == WithdrawalStatus.WAITING_CLOSE_CONFIRMATIONS:
            logger.info(f"Withdrawal {withdrawal_id}: Checking channel close confirmations")
            # Check if channels are closed by listing channels
            channels_data = await rln.list_channels()
            channels = channels_data.get("channels", [])
            
            all_closed = True
            for channel_id in withdrawal.channel_ids_to_close:
                channel_exists = any(
                    ch.get("channel_id") == channel_id
                    for ch in channels
                )
                if channel_exists:
                    # Channel still exists, check if it's closing/closed
                    channel = next(
                        (ch for ch in channels if ch.get("channel_id") == channel_id),
                        None
                    )
                    if channel:
                        status = channel.get("status", "")
                        logger.info(f"Withdrawal {withdrawal_id}: Channel {channel_id} status: {status}")
                        if status not in ["Closing", "Closed"]:
                            all_closed = False
                            logger.info(f"Withdrawal {withdrawal_id}: Channel {channel_id} not yet closed, waiting...")
                            break
                    else:
                        logger.info(f"Withdrawal {withdrawal_id}: Channel {channel_id} no longer exists (closed)")
                else:
                    logger.info(f"Withdrawal {withdrawal_id}: Channel {channel_id} no longer in channel list (closed)")
            
            if all_closed:
                logger.info(f"Withdrawal {withdrawal_id}: All channels closed, moving to waiting for balance update")
                # Store when we started waiting
                withdrawal.balance_wait_started_at = int(datetime.utcnow().timestamp())
                save_withdrawal(withdrawal)
                
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.WAITING_BALANCE_UPDATE
                )
                withdrawal = get_withdrawal(withdrawal_id)
                # Continue to check balance immediately
            else:
                logger.info(f"Withdrawal {withdrawal_id}: Still waiting for channel closures")
                return  # Don't continue if channels aren't closed yet
        
        if withdrawal.status == WithdrawalStatus.WAITING_BALANCE_UPDATE:
            # Check timeout (10 minutes = 600 seconds)
            now = int(datetime.utcnow().timestamp())
            wait_started_at = withdrawal.balance_wait_started_at or withdrawal.updated_at
            elapsed_seconds = now - wait_started_at
            timeout_seconds = 600  # 10 minutes
            
            if elapsed_seconds >= timeout_seconds:
                logger.warning(f"Withdrawal {withdrawal_id}: Timeout waiting for balance update ({elapsed_seconds}s)")
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.FAILED,
                    error_code="BALANCE_UPDATE_TIMEOUT",
                    error_message=f"Balance did not increase after {elapsed_seconds}s. Channel close may still be pending.",
                    retryable=True
                )
                return
            
            logger.info(f"Withdrawal {withdrawal_id}: Checking balance update (elapsed: {elapsed_seconds}s, timeout: {timeout_seconds}s)")
            
            # Refresh transfers first
            await rln.refresh_transfers(skip_sync=False)
            
            # Get current balance
            btc_balance_data = await rln.get_btc_balance()
            current_balance = btc_balance_data["vanilla"]["spendable"]
            baseline_balance = withdrawal.baseline_balance_sats or 0
            
            logger.info(f"Withdrawal {withdrawal_id}: Current balance: {current_balance} sats, Baseline: {baseline_balance} sats")
            
            if current_balance > baseline_balance:
                increase = current_balance - baseline_balance
                logger.info(f"Withdrawal {withdrawal_id}: Balance increased by {increase} sats, proceeding to sweeping")
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.SWEEPING_OUTPUTS
                )
                withdrawal = get_withdrawal(withdrawal_id)
            else:
                logger.info(f"Withdrawal {withdrawal_id}: Balance not yet increased, will check again in 40 seconds")
                # Schedule a retry after 40 seconds
                asyncio.create_task(_retry_balance_check(withdrawal_id, 40))
                return
        
        if withdrawal.status == WithdrawalStatus.SWEEPING_OUTPUTS:
            logger.info(f"Withdrawal {withdrawal_id}: Starting to sweep outputs to {withdrawal.address_or_rgbinvoice}")
            # Sweep outputs to address
            try:
                # Get current balance to determine amount
                logger.info(f"Withdrawal {withdrawal_id}: Getting BTC balance")
                btc_balance_data = await rln.get_btc_balance()
                vanilla_spendable = btc_balance_data["vanilla"]["spendable"]
                logger.info(f"Withdrawal {withdrawal_id}: Vanilla spendable balance: {vanilla_spendable} sats")
                
                # Use requested amount or max available
                amount_sats = withdrawal.amount_sats_requested
                if amount_sats is None:
                    amount_sats = vanilla_spendable
                    logger.info(f"Withdrawal {withdrawal_id}: No amount specified, using max available: {amount_sats} sats")
                else:
                    logger.info(f"Withdrawal {withdrawal_id}: Using requested amount: {amount_sats} sats")
                
                # Deduct fee if requested
                if withdrawal.deduct_fee_from_amount:
                    # Estimate fee (simplified - in production use proper fee estimation)
                    estimated_fee = 1000  # Rough estimate
                    amount_sats = max(0, amount_sats - estimated_fee)
                    withdrawal.fee_sats = estimated_fee
                    logger.info(f"Withdrawal {withdrawal_id}: Deducting fee {estimated_fee} sats, final amount: {amount_sats} sats")
                else:
                    withdrawal.fee_sats = None
                    logger.info(f"Withdrawal {withdrawal_id}: Fee will be added on top")
                
                # Use fee_rate from request or default
                fee_rate = withdrawal.fee_rate_sat_per_vb or 5
                logger.info(f"Withdrawal {withdrawal_id}: Using fee_rate: {fee_rate} sat/vb")
                
                # Send BTC
                logger.info(f"Withdrawal {withdrawal_id}: Sending {amount_sats} sats to {withdrawal.address_or_rgbinvoice}")
                txid = await rln.send_btc(
                    address=withdrawal.address_or_rgbinvoice,
                    amount=amount_sats,
                    fee_rate=fee_rate,
                    skip_sync=False
                )
                logger.info(f"Withdrawal {withdrawal_id}: Transaction broadcasted, txid: {txid}")
                
                withdrawal.sweep_txid = txid
                withdrawal.amount_sats_sent = amount_sats
                save_withdrawal(withdrawal)
                
                logger.info(f"Withdrawal {withdrawal_id}: Updating status to BROADCASTED")
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.BROADCASTED
                )
                withdrawal = get_withdrawal(withdrawal_id)
                
            except Exception as e:
                logger.error(f"Withdrawal {withdrawal_id}: Error sweeping outputs: {e}")
                update_withdrawal_status(
                    withdrawal_id,
                    WithdrawalStatus.FAILED,
                    error_code="SWEEP_FAILED",
                    error_message=str(e),
                    retryable=True
                )
                return
        
        if withdrawal.status == WithdrawalStatus.BROADCASTED:
            logger.info(f"Withdrawal {withdrawal_id}: Transaction broadcasted, marking as confirmed")
            # Mark as confirmed (in production, would wait for confirmations)
            update_withdrawal_status(
                withdrawal_id,
                WithdrawalStatus.CONFIRMED
            )
            logger.info(f"Withdrawal {withdrawal_id}: Withdrawal completed successfully")
    
    except Exception as e:
        logger.error(f"Withdrawal {withdrawal_id}: Error processing withdrawal: {e}", exc_info=True)
        update_withdrawal_status(
            withdrawal_id,
            WithdrawalStatus.FAILED,
            error_code="PROCESSING_ERROR",
            error_message=str(e),
            retryable=True
        )

