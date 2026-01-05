"""Module containing models related to Deposit and UTEXO operations."""
from typing import Optional, Literal
from enum import Enum
from pydantic import BaseModel
from src.lightning.model import LightningAsset


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
    addresses: list[SingleUseDepositAddressResponse]


class WithdrawFromUTEXORequestModel(BaseModel):
    """Request model for withdrawing from UTEXO."""
    address_or_rgbinvoice: str
    amount_sats: Optional[int] = None  # Required for BTC withdrawal
    fee_rate: int
    asset: Optional[LightningAsset] = None  # Required for Asset withdrawal


class WithdrawFromUTEXOResponse(BaseModel):
    """Response model for UTEXO withdrawal."""
    withdrawal_id: str
    txid: Optional[str] = None


class WithdrawalStatus(str, Enum):
    """Withdrawal status enum."""
    REQUESTED = "REQUESTED"
    CLOSING_CHANNELS = "CLOSING_CHANNELS"
    WAITING_CLOSE_CONFIRMATIONS = "WAITING_CLOSE_CONFIRMATIONS"
    WAITING_BALANCE_UPDATE = "WAITING_BALANCE_UPDATE"
    SWEEPING_OUTPUTS = "SWEEPING_OUTPUTS"
    BROADCASTED = "BROADCASTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class WithdrawRequestModel(BaseModel):
    """Request model for withdraw orchestrator."""
    address_or_rgbinvoice: str
    amount_sats: Optional[int] = None  # Required for BTC withdrawal
    asset: Optional[LightningAsset] = None  # Required for Asset withdrawal
    fee_rate: int
    deduct_fee_from_amount: bool = True


class WithdrawResponse(BaseModel):
    """Response model for withdraw request."""
    withdrawal_id: str
    status: WithdrawalStatus


class WithdrawalState(BaseModel):
    """Model for withdrawal state storage."""
    withdrawal_id: str
    idempotency_key: str
    address_or_rgbinvoice: str
    amount_sats_requested: Optional[int]
    amount_sats_sent: Optional[int] = None
    asset: Optional[LightningAsset] = None
    source: str
    channel_ids_to_close: list[str] = []
    close_txids: list[str] = []
    sweep_txid: Optional[str] = None
    fee_sats: Optional[int] = None
    fee_rate_sat_per_vb: Optional[int] = None
    fee_rate: Optional[int] = None
    close_mode: str = "cooperative"
    deduct_fee_from_amount: bool = True
    baseline_balance_sats: Optional[int] = None  # Balance before closing channels
    balance_wait_started_at: Optional[int] = None  # When we started waiting for balance update
    status: WithdrawalStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    attempt_count: int = 0
    last_attempt_at: Optional[int] = None
    created_at: int
    updated_at: int


class GetWithdrawalResponse(BaseModel):
    """Response model for getting withdrawal status."""
    withdrawal_id: str
    status: WithdrawalStatus
    address_or_rgbinvoice: str
    amount_sats_requested: Optional[int]
    amount_sats_sent: Optional[int] = None
    asset: Optional[LightningAsset] = None
    close_txids: list[str] = []
    sweep_txid: Optional[str] = None
    fee_sats: Optional[int] = None
    timestamps: dict[str, int]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False


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

    precision: int
    balance: Balance



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

