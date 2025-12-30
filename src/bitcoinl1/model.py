"""Module containing models related to Deposit and UTEXO operations."""
from typing import Optional, Literal
from pydantic import BaseModel


class SingleUseDepositAddressResponse(BaseModel):
    """Response model for single-use deposit address."""
    btc_address: str
    asset_invoice: str
    expires_at: Optional[str] = None


class UnusedDepositAddress(BaseModel):
    """Model for unused deposit address."""
    address: str
    created_at: int


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


class BtcBalance(BaseModel):
    """Model for BTC balance details (vanilla/colored)."""
    settled: int
    future: int
    spendable: int


class Balance(BaseModel):
    """Model for asset balance details."""
    settled: int
    future: int
    spendable: int
    offchain_outbound: Optional[int] = 0
    # offchain_inbound: Optional[int] = 0


class OffchainBalanceDetail(BaseModel):
    """Model for offchain balance detail."""
    expiry_time: str
    amount: int


class OffchainBalance(BaseModel):
    """Model for offchain balance."""
    total: int
    details: list[OffchainBalanceDetail] = []


class BtcBalanceResponse(BaseModel):
    """Response model for BTC balance."""
    vanilla: BtcBalance
    colored: BtcBalance
    offchain_balance: Optional[OffchainBalance] = None


class AssetBalance(BaseModel):
    """Model for asset balance."""
    asset_id: str
    ticker: Optional[str] = None
    # name: Optional[str] = None
    # details: Optional[str] = None
    precision: int
    # issued_supply: int
    # timestamp: int
    # added_at: int
    balance: Balance
    # media: Optional[dict] = None


class WalletBalanceResponse(BaseModel):
    """Response model for wallet balance."""
    balance: BtcBalanceResponse
    asset_balances: list[AssetBalance]


class AssignmentFungible(BaseModel):
    """Model for fungible assignment."""
    type: Literal["Fungible"]
    value: int


class TransferTransportEndpoint(BaseModel):
    """Model for transfer transport endpoint."""
    endpoint: str
    transport_type: Literal["JsonRpc"]
    used: bool


class Transfer(BaseModel):
    """Model for transfer."""
    idx: int
    created_at: int
    updated_at: int
    status: Literal["WaitingCounterparty", "WaitingConfirmations", "Settled", "Failed"]
    requested_assignment: AssignmentFungible
    assignments: list[AssignmentFungible]
    kind: Literal["Issuance", "ReceiveBlind", "ReceiveWitness", "Send", "Inflation"]
    txid: str
    recipient_id: str
    receive_utxo: str
    change_utxo: Optional[str] = None
    expiration: int
    transport_endpoints: list[TransferTransportEndpoint]


class ListTransfersResponse(BaseModel):
    """Response model for list transfers."""
    transfers: list[Transfer]


class BlockTime(BaseModel):
    """Model for block confirmation time."""
    height: int
    timestamp: int


class Transaction(BaseModel):
    """Model for transaction."""
    transaction_type: Literal["RgbSend", "Drain", "CreateUtxos", "User"]
    txid: str
    received: int
    sent: int
    fee: int
    confirmation_time: BlockTime


class ListTransactionsResponse(BaseModel):
    """Response model for list transactions."""
    transactions: list[Transaction]

