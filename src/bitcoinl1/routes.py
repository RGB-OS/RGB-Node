"""Deposit and UTEXO API routes with mock implementations."""
from datetime import datetime, timedelta
from fastapi import APIRouter
from src.bitcoinl1.model import (
    SingleUseDepositAddressResponse,
    UnusedDepositAddress,
    UnusedDepositAddressesResponse,
    WithdrawFromUTEXORequestModel,
    WithdrawFromUTEXOResponse,
    WalletBalanceResponse,
    BtcBalanceResponse,
    BtcBalance,
    Balance,
    AssetBalance,
    OffchainBalance,
    OffchainBalanceDetail,
)
from src.rln_client import get_rln_client
from src.bitcoinl1.address_manager import (
    get_or_create_address,
    get_or_create_asset_invoice,
    get_cached_expires_at,
    get_deposit_address
)
from src.bitcoinl1.settlement import settle_balances
import uuid
import os

router = APIRouter(prefix="/wallet", tags=["Deposit & UTEXO"])

# Mock storage for withdrawals
withdrawals: dict[str, WithdrawFromUTEXOResponse] = {}


@router.get("/single-use-address", response_model=SingleUseDepositAddressResponse)
async def get_single_use_deposit_address() -> SingleUseDepositAddressResponse:
    """
    Returns a single-use Bitcoin deposit address associated with the UTEXOWallet.
    
    Funds sent to this address can be detected and credited to the wallet for:
    - Bitcoin L1 balance
    - UTEXO deposits
    - Asset-aware flows (RGB), depending on wallet configuration
    
    Each address is intended for one-time use only.
    
    Notes:
    - Once funds are detected, the address is considered used.
    - Reusing a single-use address is discouraged.
    - Address monitoring and crediting are handled automatically by the backend.
    - Returns cached address/invoice if available, otherwise generates new ones.
    - Address persists even if invoice is removed/used, allowing invoice regeneration.
    """
    btc_address = await get_or_create_address()
    asset_invoice = await get_or_create_asset_invoice()
    
    expires_at = get_cached_expires_at() or (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
    
    return SingleUseDepositAddressResponse(
        btc_address=btc_address,
        asset_invoice=asset_invoice,
        expires_at=expires_at
    )


@router.get("/unused-addresses", response_model=UnusedDepositAddressesResponse)
async def get_unused_deposit_addresses() -> UnusedDepositAddressesResponse:
    """
    Returns a list of unused Bitcoin deposit addresses associated with the UTEXOWallet.
    
    These addresses have been generated previously but have not yet received funds.
    
    Notes:
    - Only addresses with no detected deposits are returned.
    - Addresses may be automatically rotated or expired by the backend.
    - Recommended for wallets that pre-generate deposit addresses.
    """
    unused_addresses = []
    
    cached_address = get_deposit_address()
    if cached_address:
        unused_addresses.append(cached_address)
    
    return UnusedDepositAddressesResponse(
        addresses=unused_addresses
    )


@router.post("/withdraw-from-utexo", response_model=WithdrawFromUTEXOResponse)
async def withdraw_from_utexo(
    req: WithdrawFromUTEXORequestModel
) -> WithdrawFromUTEXOResponse:
    """
    Withdraws BTC from the UTEXO layer back to Bitcoin L1.
    
    This operation creates a Bitcoin transaction that releases funds from UTEXO 
    to a specified on-chain address.
    """
    rln = get_rln_client()
    txid = await rln.send_btc(
        address=req.address,
        amount=req.amount_sats,
        fee_rate=req.fee_rate,
        skip_sync=False
    )
    
    withdrawal_id = str(uuid.uuid4())
    
    withdrawal = WithdrawFromUTEXOResponse(
        withdrawal_id=withdrawal_id,
        txid=txid
    )
    
    withdrawals[withdrawal_id] = withdrawal
    
    return withdrawal


@router.get("/balance", response_model=WalletBalanceResponse)
async def get_balance() -> WalletBalanceResponse:
    """
    Returns the wallet balance including BTC balance and token balances.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    rln = get_rln_client()
    btc_balance_data = await rln.get_btc_balance()
    assets_data = await rln.list_assets(filter_asset_schemas=["Nia"])
    channels_data = await rln.list_channels()
    
    channels = channels_data.get("channels", [])
    total_offchain_msat = 0
    offchain_details = []
    
    for channel in channels:
        outbound_msat = channel.get("outbound_balance_msat", 0)
        total_offchain_msat += outbound_msat
        
        if outbound_msat > 0:
            # Set expiry_time to now + 1 month
            expiry_time = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
            offchain_details.append(
                OffchainBalanceDetail(
                    expiry_time=expiry_time,
                    amount=outbound_msat // 1000
                )
            )
    
    offchain_balance = OffchainBalance(
        total=total_offchain_msat // 1000,
        details=offchain_details
    )
    
    btc_balance = BtcBalanceResponse(
        vanilla=BtcBalance(**btc_balance_data["vanilla"]),
        colored=BtcBalance(**btc_balance_data["colored"]),
        offchain_balance=offchain_balance
    )
    
    asset_balances = []
    nia_assets = assets_data.get("nia", [])
    for asset in nia_assets:
        balance_data = asset.get("balance", {})
        asset_balance = AssetBalance(
            asset_id=asset["asset_id"],
            ticker=asset.get("ticker"),
            precision=asset.get("precision", 0),
            balance=Balance(
                settled=balance_data.get("settled", 0),
                future=balance_data.get("future", 0),
                spendable=balance_data.get("spendable", 0),
                offchain_outbound=balance_data.get("offchain_outbound", 0),
            ),
        )
        asset_balances.append(asset_balance)
    
    return WalletBalanceResponse(
        balance=btc_balance,
        asset_balances=asset_balances
    )


@router.post("/settle")
async def settle():
    """
    Settle on-chain balances by opening Lightning channels.
    
    - Opens BTC channel if vanilla balance spendable > 0
    - Opens asset channels for each asset with offchain_outbound < spendable
    """
    return await settle_balances()

