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
    ListTransfersResponse,
    Transfer,
    AssignmentFungible,
    TransferTransportEndpoint,
    ListTransactionsResponse,
    Transaction,
    BlockTime,
)
from src.rln_client import get_rln_client
from src.bitcoinl1.watcher import start_watcher
import uuid
import os
import hashlib
import secrets
from fastapi import HTTPException

router = APIRouter(prefix="/wallet", tags=["Deposit & UTEXO"])

# Mock storage for deposit addresses and withdrawals
deposit_addresses: list[UnusedDepositAddress] = []
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
    Each address is intended for one-time use only.
    
    Notes:
    - Once funds are detected, the address is considered used.
    - Reusing a single-use address is discouraged.
    - Address monitoring and crediting are handled automatically by the backend.
    """
    rln = get_rln_client()
    btc_address = await rln.get_address()
    
    rgb_invoice_data = await rln.create_rgb_invoice(
        min_confirmations=1,
        duration_seconds=86400,
        witness=True
    )
    asset_invoice = rgb_invoice_data.get("invoice")
    batch_transfer_idx = rgb_invoice_data.get("batch_transfer_idx")
    
    # Start background watcher for transfer status (fire-and-forget, non-blocking)
    if batch_transfer_idx is not None:
        start_watcher(batch_transfer_idx)
    
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
    
    deposit_addresses.append(
        UnusedDepositAddress(
            address=btc_address,
            created_at=datetime.utcnow().isoformat() + "Z"
        )
    )
    
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
    rln = get_rln_client()
    address = await rln.get_address()
    
    unused_addresses = []

    if address:
        unused_addresses.append(
            UnusedDepositAddress(
                address=address,
                created_at=datetime.utcnow().isoformat() + "Z"
            )
        )
    
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


@router.get("/transfers", response_model=ListTransfersResponse)
async def list_transfers() -> ListTransfersResponse:
    """
    List transfers for the configured asset ID.
    """
    asset_id = os.getenv("RLN_ASSET_ID")
    if not asset_id:
        raise ValueError("RLN_ASSET_ID environment variable must be set")
    
    rln = get_rln_client()
    transfers_data = await rln.list_transfers(asset_id)
    
    transfers = []
    for transfer_data in transfers_data.get("transfers", []):
        transfer = Transfer(
            idx=transfer_data["idx"],
            created_at=transfer_data["created_at"],
            updated_at=transfer_data["updated_at"],
            status=transfer_data["status"],
            requested_assignment=AssignmentFungible(**transfer_data["requested_assignment"]),
            assignments=[AssignmentFungible(**a) for a in transfer_data.get("assignments", [])],
            kind=transfer_data["kind"],
            txid=transfer_data["txid"],
            recipient_id=transfer_data["recipient_id"],
            receive_utxo=transfer_data["receive_utxo"],
            change_utxo=transfer_data.get("change_utxo"),
            expiration=transfer_data["expiration"],
            transport_endpoints=[
                TransferTransportEndpoint(**ep) for ep in transfer_data.get("transport_endpoints", [])
            ]
        )
        transfers.append(transfer)
    
    return ListTransfersResponse(transfers=transfers)


@router.get("/transactions", response_model=ListTransactionsResponse)
async def list_transactions() -> ListTransactionsResponse:
    """
    List transactions from the wallet.
    """
    rln = get_rln_client()
    transactions_data = await rln.list_transactions(skip_sync=False)
    
    transactions = []
    for tx_data in transactions_data.get("transactions", []):
        confirmation_time_data = tx_data.get("confirmation_time", {})
        
        transaction = Transaction(
            transaction_type=tx_data["transaction_type"],
            txid=tx_data["txid"],
            received=tx_data.get("received", 0),
            sent=tx_data.get("sent", 0),
            fee=tx_data.get("fee", 0),
            confirmation_time=BlockTime(
                height=confirmation_time_data.get("height", 0),
                timestamp=confirmation_time_data.get("timestamp", 0)
            )
        )
        transactions.append(transaction)
    
    return ListTransactionsResponse(transactions=transactions)


@router.post("/settle")
async def settle():
    """
    Settle on-chain balances by opening Lightning channels.
    
    - Opens BTC channel if vanilla balance spendable > 0
    - Opens asset channels for each asset with offchain_outbound > 0
    """
    import logging
    logger = logging.getLogger(__name__)
    
    lsp_peer = os.getenv("RLN_LSP_PEER")
    if not lsp_peer:
        raise HTTPException(
            status_code=400,
            detail="RLN_LSP_PEER environment variable must be set"
        )
    
    rln = get_rln_client()
    
    # Get current balance
    btc_balance_data = await rln.get_btc_balance()
    assets_data = await rln.list_assets(filter_asset_schemas=["Nia"])
    
    results = []
    
    # Generate temporary_channel_id (SHA256 of random 32 bytes)
    def generate_temporary_channel_id() -> str:
        random_bytes = secrets.token_bytes(32)
        return hashlib.sha256(random_bytes).hexdigest()
    
    # Fee reserve for channel opening (on-chain transaction fees)
    # Typical channel opening needs ~500-2000 sats for fees depending on network conditions
    CHANNEL_OPEN_FEE_RESERVE = 2000  # Reserve 2000 sats for fees
    
    # 1. Open BTC channel if vanilla balance > 0
    vanilla_spendable = btc_balance_data.get("vanilla", {}).get("spendable", 0)
    if vanilla_spendable > CHANNEL_OPEN_FEE_RESERVE:
        # Reserve fees from capacity - channel capacity should be less than spendable
        channel_capacity = vanilla_spendable - CHANNEL_OPEN_FEE_RESERVE
        
        btc_channel_config = {
            "peer_pubkey_and_opt_addr": lsp_peer,
            "capacity_sat": channel_capacity,
            "push_msat": 0,
            "public": True,
            "with_anchors": True,
            "fee_base_msat": 1000,
            "fee_proportional_millionths": 0,
            "temporary_channel_id": generate_temporary_channel_id()
        }
        
        try:
            btc_channel_result = await rln.open_channel(btc_channel_config)
            results.append({
                "type": "btc",
                "capacity_sat": channel_capacity,
                "fee_reserve": CHANNEL_OPEN_FEE_RESERVE,
                "result": btc_channel_result
            })
            logger.info(f"Opened BTC channel with capacity {channel_capacity} sats (reserved {CHANNEL_OPEN_FEE_RESERVE} sats for fees)")
        except Exception as e:
            logger.error(f"Failed to open BTC channel: {e}")
            results.append({
                "type": "btc",
                "capacity_sat": channel_capacity,
                "fee_reserve": CHANNEL_OPEN_FEE_RESERVE,
                "error": str(e)
            })
    elif vanilla_spendable > 0:
        logger.warning(f"Insufficient balance to open BTC channel: {vanilla_spendable} sats available, need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats")
        results.append({
            "type": "btc",
            "error": f"Insufficient balance: {vanilla_spendable} sats available, need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats (including fee reserve)"
        })
    
    # 2. Open asset channels if offchain_outbound < spendable
    # Open channel for the difference: spendable - offchain_outbound
    nia_assets = assets_data.get("nia", [])
    for asset in nia_assets:
        balance_data = asset.get("balance", {})
        offchain_outbound = balance_data.get("offchain_outbound", 0)
        spendable = balance_data.get("spendable", 0)
        
        if offchain_outbound < spendable:
            asset_id = asset.get("asset_id")
            amount_to_settle = spendable - offchain_outbound
            
            if not asset_id:
                logger.warning(f"Skipping asset channel: missing asset_id")
                continue
            
            if amount_to_settle <= 0:
                logger.debug(f"Skipping asset channel for {asset_id}: no amount to settle")
                continue
            
            # Use vanilla balance for capacity_sat (same as BTC channel)
            # Asset channels need BTC capacity to open, skip if no vanilla balance
            if vanilla_spendable <= CHANNEL_OPEN_FEE_RESERVE:
                logger.warning(f"Skipping asset channel for {asset_id}: insufficient vanilla balance for channel capacity (need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats)")
                results.append({
                    "type": "asset",
                    "asset_id": asset_id,
                    "asset_amount": amount_to_settle,
                    "error": f"Insufficient vanilla balance: {vanilla_spendable} sats available, need at least {CHANNEL_OPEN_FEE_RESERVE + 1} sats (including fee reserve)"
                })
                continue
            
            # Reserve fees from capacity
            asset_channel_capacity = vanilla_spendable - CHANNEL_OPEN_FEE_RESERVE
            
            asset_channel_config = {
                "peer_pubkey_and_opt_addr": lsp_peer,
                "capacity_sat": asset_channel_capacity,
                "push_msat": 0,
                "public": True,
                "with_anchors": True,
                "fee_base_msat": 1000,
                "fee_proportional_millionths": 0,
                "temporary_channel_id": generate_temporary_channel_id(),
                "asset_id": asset_id,
                "asset_amount": amount_to_settle
            }
            
            try:
                asset_channel_result = await rln.open_channel(asset_channel_config)
                results.append({
                    "type": "asset",
                    "asset_id": asset_id,
                    "asset_amount": amount_to_settle,
                    "result": asset_channel_result
                })
                logger.info(f"Opened asset channel for {asset_id} with amount {amount_to_settle} (spendable: {spendable}, offchain_outbound: {offchain_outbound})")
            except Exception as e:
                logger.error(f"Failed to open asset channel for {asset_id}: {e}")
                results.append({
                    "type": "asset",
                    "asset_id": asset_id,
                    "asset_amount": amount_to_settle,
                    "error": str(e)
                })
    
    return {
        "results": results,
        "total_channels_opened": len([r for r in results if "error" not in r])
    }

