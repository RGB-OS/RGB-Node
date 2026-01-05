"""Deposit and UTEXO API routes with mock implementations."""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
import json
import base64
import hashlib
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
    WithdrawRequestModel,
    WithdrawResponse,
    GetWithdrawalResponse,
    WithdrawalState,
    WithdrawalStatus,
)
from src.lightning.model import LightningAsset
from src.rln_client import get_rln_client
from src.bitcoinl1.address_manager import (
    get_or_create_address,
    get_or_create_asset_invoice,
    get_cached_expires_at,
    get_deposit_address
)
from src.bitcoinl1.settlement import settle_balances
from src.bitcoinl1.withdrawal import withdraw_asset, withdraw_btc
from src.bitcoinl1.watcher import start_watcher
from src.bitcoinl1.withdrawal_storage import (
    get_withdrawal,
    get_withdrawal_by_idempotency_key,
    save_withdrawal
)
from src.bitcoinl1.withdrawal_orchestrator import process_withdrawal
from src.routes import SendAssetEndRequestModel
import uuid
import os
import asyncio

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
    btc_address = await get_or_create_address()
    asset_invoice = await get_or_create_asset_invoice()
    
    expires_at = get_cached_expires_at() or (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
    
    unused_address = SingleUseDepositAddressResponse(
        btc_address=btc_address,
        asset_invoice=asset_invoice,
        expires_at=expires_at
    )
    
    return UnusedDepositAddressesResponse(addresses=[unused_address])


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


@router.post("/withdraw-begin", response_model=str)
async def withdraw_begin(
    req: WithdrawRequestModel
) -> str:
    """
    Begins a withdrawal process.
    
    Returns the request encoded as base64 (mock PSBT).
    Later this should construct and return a real base64 PSBT.
    """
    # Validate request based on flow type
    if req.address_or_rgbinvoice.startswith("rgb:"):
        # Asset flow - asset is required
        if req.asset is None:
            raise HTTPException(
                status_code=400,
                detail="asset is required when address_or_rgbinvoice is an RGB invoice"
            )
    else:
        # BTC flow - amount_sats is required
        if req.amount_sats is None:
            raise HTTPException(
                status_code=400,
                detail="amount_sats is required for BTC withdrawal"
            )
    
    request_dict = req.model_dump()
    request_json = json.dumps(request_dict)
    psbt_base64 = base64.b64encode(request_json.encode('utf-8')).decode('utf-8')
    return psbt_base64


@router.post("/withdraw-end", response_model=WithdrawResponse)
async def withdraw_end(
    req: SendAssetEndRequestModel
) -> WithdrawResponse:
    """
    Completes a withdrawal using signed PSBT.
    
    Decodes the signed_psbt (base64) back to the original request
    and processes the withdrawal.
    """
    try:
        request_json = base64.b64decode(req.signed_psbt.encode('utf-8')).decode('utf-8')
        request_dict = json.loads(request_json)
        withdraw_req = WithdrawRequestModel(**request_dict)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signed_psbt format: {str(e)}"
        )
    
    # Validate request based on flow type
    if withdraw_req.address_or_rgbinvoice.startswith("rgb:"):
        # Asset flow - asset is required
        if withdraw_req.asset is None:
            raise HTTPException(
                status_code=400,
                detail="asset is required when address_or_rgbinvoice is an RGB invoice"
            )
        
        # Use orchestrator for asset withdrawals
        # Generate idempotency key based on request parameters
        request_hash = hashlib.sha256(
            json.dumps(withdraw_req.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        idempotency_key = f"withdraw_{request_hash}"
        
        # Check for existing withdrawal with same idempotency_key
        existing = get_withdrawal_by_idempotency_key(idempotency_key)
        if existing:
            return WithdrawResponse(
                withdrawal_id=existing.withdrawal_id,
                status=existing.status
            )
        
        # Create new withdrawal
        withdrawal_id = str(uuid.uuid4())
        now = int(datetime.utcnow().timestamp())
        
        withdrawal = WithdrawalState(
            withdrawal_id=withdrawal_id,
            idempotency_key=idempotency_key,
            address_or_rgbinvoice=withdraw_req.address_or_rgbinvoice,
            amount_sats_requested=None,  # Not applicable for assets
            asset=withdraw_req.asset,
            source="channels_only",  # Hardcoded
            channel_ids_to_close=[],  # Will be determined by orchestrator
            fee_rate_sat_per_vb=None,  # Not applicable for assets
            fee_rate=withdraw_req.fee_rate,
            close_mode="cooperative",  # Always cooperative
            deduct_fee_from_amount=withdraw_req.deduct_fee_from_amount,
            status=WithdrawalStatus.REQUESTED,
            created_at=now,
            updated_at=now
        )
        
        save_withdrawal(withdrawal)
        
        # Start processing in background
        asyncio.create_task(process_withdrawal(withdrawal_id))
        
        return WithdrawResponse(
            withdrawal_id=withdrawal_id,
            status=WithdrawalStatus.REQUESTED
        )
    else:
        # BTC flow - amount_sats is required
        if withdraw_req.amount_sats is None:
            raise HTTPException(
                status_code=400,
                detail="amount_sats is required for BTC withdrawal"
            )
        
        # Generate idempotency key based on request parameters
        request_hash = hashlib.sha256(
            json.dumps(withdraw_req.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        idempotency_key = f"withdraw_{request_hash}"
        
        # Check for existing withdrawal with same idempotency_key
        existing = get_withdrawal_by_idempotency_key(idempotency_key)
        if existing:
            return WithdrawResponse(
                withdrawal_id=existing.withdrawal_id,
                status=existing.status
            )
        
        # Create new withdrawal
        withdrawal_id = str(uuid.uuid4())
        now = int(datetime.utcnow().timestamp())
        
        withdrawal = WithdrawalState(
            withdrawal_id=withdrawal_id,
            idempotency_key=idempotency_key,
            address_or_rgbinvoice=withdraw_req.address_or_rgbinvoice,
            amount_sats_requested=withdraw_req.amount_sats,
            asset=withdraw_req.asset,
            source="channels_only",  # Hardcoded
            channel_ids_to_close=[],  # Will be determined by orchestrator
            fee_rate_sat_per_vb=withdraw_req.fee_rate,
            fee_rate=withdraw_req.fee_rate,
            close_mode="cooperative",  # Always cooperative
            deduct_fee_from_amount=withdraw_req.deduct_fee_from_amount,
            status=WithdrawalStatus.REQUESTED,
            created_at=now,
            updated_at=now
        )
        
        save_withdrawal(withdrawal)
        
        # Start processing in background
        asyncio.create_task(process_withdrawal(withdrawal_id))
        
        return WithdrawResponse(
            withdrawal_id=withdrawal_id,
            status=WithdrawalStatus.REQUESTED
        )


@router.get("/withdraw/{withdrawal_id}", response_model=GetWithdrawalResponse)
async def get_withdrawal_status(withdrawal_id: str) -> GetWithdrawalResponse:
    """
    Get withdrawal status by ID.
    """
    withdrawal = get_withdrawal(withdrawal_id)
    if not withdrawal:
        raise HTTPException(
            status_code=404,
            detail="Withdrawal not found"
        )
    
    return GetWithdrawalResponse(
        withdrawal_id=withdrawal.withdrawal_id,
        status=withdrawal.status,
        address_or_rgbinvoice=withdrawal.address_or_rgbinvoice,
        amount_sats_requested=withdrawal.amount_sats_requested,
        amount_sats_sent=withdrawal.amount_sats_sent,
        asset=withdrawal.asset,
        close_txids=withdrawal.close_txids,
        sweep_txid=withdrawal.sweep_txid,
        fee_sats=withdrawal.fee_sats,
        timestamps={
            "created_at": withdrawal.created_at,
            "updated_at": withdrawal.updated_at
        },
        error_code=withdrawal.error_code,
        error_message=withdrawal.error_message,
        retryable=withdrawal.retryable
    )

