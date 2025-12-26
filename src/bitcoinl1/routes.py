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
    Balance,
    TokenBalance,
)
from src.rln_client import get_rln_client
import uuid

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
    """
    rln = get_rln_client()
    address = await rln.get_address()
    
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
    
    deposit_addresses.append(
        UnusedDepositAddress(
            address=address,
            created_at=datetime.utcnow().isoformat() + "Z"
        )
    )
    
    return SingleUseDepositAddressResponse(
        address=address,
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
    
    btc_balance = BtcBalanceResponse(
        vanilla=Balance(**btc_balance_data["vanilla"]),
        colored=Balance(**btc_balance_data["colored"])
    )
    
    token_balances = []
    nia_assets = assets_data.get("nia", [])
    for asset in nia_assets:
        balance_data = asset.get("balance", {})
        token_balance = TokenBalance(
            asset_id=asset["asset_id"],
            ticker=asset.get("ticker"),
            name=asset.get("name"),
            details=asset.get("details"),
            precision=asset["precision"],
            issued_supply=asset["issued_supply"],
            timestamp=asset["timestamp"],
            added_at=asset["added_at"],
            balance=Balance(
                settled=balance_data.get("settled", 0),
                future=balance_data.get("future", 0),
                spendable=balance_data.get("spendable", 0),
                offchain_outbound=balance_data.get("offchain_outbound", 0),
                offchain_inbound=balance_data.get("offchain_inbound", 0)
            ),
            media=asset.get("media")
        )
        token_balances.append(token_balance)
    
    return WalletBalanceResponse(
        balance=btc_balance,
        token_balances=token_balances
    )

