"""Module containing models related to Deposit and UTEXO operations."""
from typing import Optional
from pydantic import BaseModel


class SingleUseDepositAddressResponse(BaseModel):
    """Response model for single-use deposit address."""
    address: str
    expires_at: Optional[str] = None


class UnusedDepositAddress(BaseModel):
    """Model for unused deposit address."""
    address: str
    created_at: str


class UnusedDepositAddressesResponse(BaseModel):
    """Response model for unused deposit addresses."""
    addresses: list[UnusedDepositAddress]


class WithdrawFromUTEXORequestModel(BaseModel):
    """Request model for withdrawing from UTEXO."""
    address: str
    amount_sats: int  # Using int instead of bigint for JSON compatibility
    fee_rate: int


class WithdrawFromUTEXOResponse(BaseModel):
    """Response model for UTEXO withdrawal."""
    withdrawal_id: str
    txid: Optional[str] = None


class Balance(BaseModel):
    """Model for balance details."""
    settled: int
    future: int
    spendable: int
    offchain_outbound: Optional[int] = 0
    offchain_inbound: Optional[int] = 0


class BtcBalanceResponse(BaseModel):
    """Response model for BTC balance."""
    vanilla: Balance
    colored: Balance


class TokenBalance(BaseModel):
    """Model for token balance."""
    asset_id: str
    ticker: Optional[str] = None
    name: Optional[str] = None
    details: Optional[str] = None
    precision: int
    issued_supply: int
    timestamp: int
    added_at: int
    balance: Balance
    media: Optional[dict] = None


class WalletBalanceResponse(BaseModel):
    """Response model for wallet balance."""
    balance: BtcBalanceResponse
    token_balances: list[TokenBalance]

