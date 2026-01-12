"""Deposit and UTEXO API routes with mock implementations."""
from datetime import datetime, timedelta
from typing import Tuple
from fastapi import APIRouter, HTTPException, Depends
from rgb_lib import Wallet, Assignment
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
    ReceiveRequestModel,
    ReceiveResponseModel,
    PayBeginRequestModel,
    PayEndRequestModel,
    PayResponseModel,
)
from src.lightning.model import LightningAsset, CreateLightningInvoiceRequestModel
from src.lightning.routes import create_lightning_invoice
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
from src.dependencies import get_wallet
import uuid
import os
import asyncio

router = APIRouter(prefix="/lightning", tags=["Deposit & UTEXO"])

# Mock storage for withdrawals
withdrawals: dict[str, WithdrawFromUTEXOResponse] = {}
psbt_to_withdraw_map: dict[str, str] = {}
# Map PSBT to invoice for pay flow
psbt_to_invoice_map: dict[str, str] = {}
# Storage for receive requests
receive_requests: dict[str, ReceiveResponseModel] = {}
# Storage for payment requests
payment_requests: dict[str, PayResponseModel] = {}

@router.get("/onchain-receive", response_model=SingleUseDepositAddressResponse)
async def get_single_use_deposit_address(
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> SingleUseDepositAddressResponse:
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
async def get_unused_deposit_addresses(
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> UnusedDepositAddressesResponse:
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
async def get_balance(
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> WalletBalanceResponse:
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
async def settle(
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
):
    """
    Settle on-chain balances by opening Lightning channels.
    
    - Opens BTC channel if vanilla balance spendable > 0
    - Opens asset channels for each asset with offchain_outbound < spendable
    """
    return await settle_balances()


@router.post("/onchain-send-begin", response_model=str)
async def withdraw_begin(
    req: WithdrawRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> str:
    """
    Begins a withdrawal process.
    
    Returns the request encoded as base64 (mock PSBT).
    Later this should construct and return a real base64 PSBT.
    """
    wallet, online, xpub_van, xpub_col = wallet_dep

    if req.address_or_rgbinvoice.startswith("rgb:"):
        if req.asset is None:
            raise HTTPException(
                status_code=400,
                detail="asset is required when address_or_rgbinvoice is an RGB invoice"
            )
    else:
        if req.amount_sats is None:
            raise HTTPException(
                status_code=400,
                detail="amount_sats is required for BTC withdrawal"
            )
    
    request_dict = req.model_dump()
    request_json = json.dumps(request_dict)
    psbt_base64 = base64.b64encode(request_json.encode('utf-8')).decode('utf-8')

    amount_sats = req.amount_sats if req.amount_sats is not None else 1000
    psbt = wallet.send_btc_begin(online, 'bcrt1ppjggtsju3sj62ylyq0062ml9hmptcuf2gg4e47m3ntyj7dyrgdfqzg5epw', amount_sats, 5, True)
    psbt_to_withdraw_map[xpub_van] = psbt_base64
    return psbt


@router.post("/onchain-send-end", response_model=WithdrawResponse)
async def withdraw_end(
    req: SendAssetEndRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> WithdrawResponse:
    """
    Completes a withdrawal using signed PSBT.
    
    Decodes the signed_psbt (base64) back to the original request
    and processes the withdrawal.
    """
    wallet, online, xpub_van, xpub_col = wallet_dep
    psbt_to_use = psbt_to_withdraw_map.get(xpub_van)
    if not psbt_to_use:
        raise HTTPException(
            status_code=400,
            detail="No PSBT found. Please call /withdraw-begin first to create a PSBT."
        )
    wallet.finalize_psbt(req.signed_psbt)
    try:
        request_json = base64.b64decode(psbt_to_use.encode('utf-8')).decode('utf-8')
        request_dict = json.loads(request_json)
        withdraw_req = WithdrawRequestModel(**request_dict)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signed_psbt format: {str(e)}"
        )
    
    if withdraw_req.address_or_rgbinvoice.startswith("rgb:"):
        if withdraw_req.asset is None:
            raise HTTPException(
                status_code=400,
                detail="asset is required when address_or_rgbinvoice is an RGB invoice"
            )
        
        request_hash = hashlib.sha256(
            json.dumps(withdraw_req.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        idempotency_key = f"withdraw_{request_hash}"
        
        existing = get_withdrawal_by_idempotency_key(idempotency_key)
        if existing:
            return WithdrawResponse(
                withdrawal_id=existing.withdrawal_id,
                status=existing.status
            )
        
        withdrawal_id = str(uuid.uuid4())
        now = int(datetime.utcnow().timestamp())
        
        withdrawal = WithdrawalState(
            withdrawal_id=withdrawal_id,
            idempotency_key=idempotency_key,
            address_or_rgbinvoice=withdraw_req.address_or_rgbinvoice,
            amount_sats_requested=None,
            asset=withdraw_req.asset,
            source="channels_only",
            channel_ids_to_close=[],
            fee_rate_sat_per_vb=None,
            fee_rate=withdraw_req.fee_rate,
            close_mode="cooperative",
            deduct_fee_from_amount=withdraw_req.deduct_fee_from_amount,
            status=WithdrawalStatus.REQUESTED,
            created_at=now,
            updated_at=now
        )
        
        save_withdrawal(withdrawal)
        
        asyncio.create_task(process_withdrawal(withdrawal_id))
        
        return WithdrawResponse(
            withdrawal_id=withdrawal_id,
            status=WithdrawalStatus.REQUESTED
        )
    else:
        if withdraw_req.amount_sats is None:
            raise HTTPException(
                status_code=400,
                detail="amount_sats is required for BTC withdrawal"
            )
        
        request_hash = hashlib.sha256(
            json.dumps(withdraw_req.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        idempotency_key = f"withdraw_{request_hash}"
        
        existing = get_withdrawal_by_idempotency_key(idempotency_key)
        if existing:
            return WithdrawResponse(
                withdrawal_id=existing.withdrawal_id,
                status=existing.status
            )
        
        withdrawal_id = str(uuid.uuid4())
        now = int(datetime.utcnow().timestamp())
        
        withdrawal = WithdrawalState(
            withdrawal_id=withdrawal_id,
            idempotency_key=idempotency_key,
            address_or_rgbinvoice=withdraw_req.address_or_rgbinvoice,
            amount_sats_requested=withdraw_req.amount_sats,
            asset=withdraw_req.asset,
            source="channels_only",
            channel_ids_to_close=[],
            fee_rate_sat_per_vb=withdraw_req.fee_rate,
            fee_rate=withdraw_req.fee_rate,
            close_mode="cooperative",
            deduct_fee_from_amount=withdraw_req.deduct_fee_from_amount,
            status=WithdrawalStatus.REQUESTED,
            created_at=now,
            updated_at=now
        )
        
        save_withdrawal(withdrawal)
        
        asyncio.create_task(process_withdrawal(withdrawal_id))
        
        return WithdrawResponse(
            withdrawal_id=withdrawal_id,
            status=WithdrawalStatus.REQUESTED
        )


@router.get("/withdraw/{withdrawal_id}", response_model=GetWithdrawalResponse)
async def get_withdrawal_status(
    withdrawal_id: str,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> GetWithdrawalResponse:
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


@router.post("/receive", response_model=ReceiveResponseModel)
async def receive(
    req: ReceiveRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> ReceiveResponseModel:
    """
    Creates a receive address or invoice for receiving BTC or asset payments.
    
    Returns the same structure as /single-use-address with an additional ln_invoice field.
    """
    single_use_response = await get_single_use_deposit_address(wallet_dep)
    
    ln_invoice = ""
    request_id = None
    try:
        lightning_req = CreateLightningInvoiceRequestModel(
            amount_sats=req.amount_sat,
            asset=req.asset,
            expiry_seconds=420  # Default expiry
        )
        
        lightning_response = await create_lightning_invoice(lightning_req, wallet_dep)
        ln_invoice = lightning_response.invoice
        request_id = lightning_response.id
    except Exception as e:
        print(f"Failed to create lightning invoice: {str(e)}")
    
    return ReceiveResponseModel(
        btc_address=single_use_response.btc_address,
        asset_invoice=single_use_response.asset_invoice,
        expires_at=single_use_response.expires_at,
        ln_invoice=ln_invoice,
        request_id=request_id
    )


@router.post("/paybegin", response_model=str)
async def pay_begin(
    req: PayBeginRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> str:
    """
    Begins a payment process.
    
    Returns a PSBT that needs to be signed.
    """
    wallet, online, xpub_van, xpub_col = wallet_dep
    rln = get_rln_client()
    
    if req.address_or_invoice.startswith("rgb:"):
        # Asset payment using RGB invoice
        if req.asset is None:
            raise HTTPException(
                status_code=400,
                detail="asset is required when address_or_invoice is an RGB invoice"
            )
        
        # Decode RGB invoice
        invoice_data = await rln.decode_rgb_invoice(req.address_or_invoice)
        recipient_id = invoice_data.get("recipient_id")
        transport_endpoints = invoice_data.get("transport_endpoints", [])
        
        if not recipient_id:
            raise HTTPException(
                status_code=400,
                detail="Invalid RGB invoice: missing recipient_id"
            )
        
        from src.rgb_model import Recipient, SendAssetBeginModel
        
        assignment = Assignment.FUNGIBLE(req.asset.amount)
        recipient_map = {
            req.asset.asset_id: [
                Recipient(
                    recipient_id=recipient_id,
                    assignment=assignment,
                    witness_data=None,
                    transport_endpoints=transport_endpoints
                )
            ]
        }
        
        send_model = SendAssetBeginModel(
            recipient_map=recipient_map,
            donation=False,
            fee_rate=req.fee_rate,
            min_confirmations=req.min_confirmations
        )
        
        psbt = wallet.send_begin(
            online,
            send_model.recipient_map,
            send_model.donation,
            send_model.fee_rate,
            send_model.min_confirmations
        )
    else:
        # BTC payment to address
        if req.amount_sats is None:
            raise HTTPException(
                status_code=400,
                detail="amount_sats is required for BTC payment"
            )
        
        psbt = wallet.send_btc_begin(
            online,
            req.address_or_invoice,
            req.amount_sats,
            req.fee_rate,
            True  # skip_sync
        )
    
    # Map the PSBT to the invoice/address for later use in payend
    psbt_to_invoice_map[xpub_van] = req.address_or_invoice
    
    return psbt


@router.post("/payend", response_model=PayResponseModel)
async def pay_end(
    req: PayEndRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> PayResponseModel:
    """
    Completes a payment using signed PSBT.
    """
    wallet, online, xpub_van, xpub_col = wallet_dep
    
    # Get the original invoice/address mapped to this PSBT
    invoice_to_use = psbt_to_invoice_map.get(xpub_van)
    
    if not invoice_to_use:
        raise HTTPException(
            status_code=400,
            detail="No invoice found. Please call /paybegin first to create a PSBT."
        )
    
    # Finalize the PSBT
    wallet.finalize_psbt(req.signed_psbt)
    
    # Determine payment type
    payment_type = "ASSET" if invoice_to_use.startswith("rgb:") else "BTC"
    
    # Send the payment
    rln = get_rln_client()
    payment_id = str(uuid.uuid4())
    
    if payment_type == "ASSET":
        # For asset payments, the send_begin already initiated the transfer
        # We just need to complete it with send_end
        result = wallet.send_end(online, req.signed_psbt, False)
        txid = result.txid if hasattr(result, 'txid') else None
    else:
        # For BTC payments, use send_btc_end to complete the transaction
        result = wallet.send_btc_end(online, req.signed_psbt, False)
        txid = result.txid if hasattr(result, 'txid') else None
    
    payment_request = PayResponseModel(
        id=payment_id,
        status="SUCCEEDED" if txid else "PENDING",
        payment_type=payment_type,
        amount_sats=None,  # Could be extracted from request if needed
        asset=None,  # Could be extracted from request if needed
        fee_sats=None,
        txid=txid,
        created_at=datetime.utcnow().isoformat() + "Z"
    )
    
    payment_requests[payment_id] = payment_request
    
    # Remove the invoice from mapping after it's been used
    psbt_to_invoice_map.pop(xpub_van, None)
    
    return payment_request

