# pylint: disable=too-few-public-methods
"""Module containing models related to RGB."""
from __future__ import annotations

from datetime import datetime
import enum
from typing import List, Optional

from pydantic import BaseModel
from pydantic import model_validator

from src.constant import FEE_RATE_FOR_CREATE_UTXOS
from src.constant import NO_OF_UTXO
from src.constant import RGB_INVOICE_DURATION_SECONDS
from src.constant import UTXO_SIZE_SAT
from rgb_lib import Wallet, TransferStatus,TransportType, TransferKind
# -------------------- Helper models -----------------------

class CommonException(Exception):
    pass


class StatusModel(BaseModel):
    """Response status model."""

    status: bool


class TransactionTxModel(BaseModel):
    """Mode for get single transaction method of asset detail page service"""
    tx_id: str | None = None
    idx: int | None = None

    # 'mode='before'' ensures the validator runs before others
    @model_validator(mode='before')
    def check_at_least_one(cls, values):  # pylint: disable=no-self-argument
        """
        Ensures that at least one of tx_id or idx is provided.
        """
        tx_id, idx = values.get('tx_id'), values.get('idx')
        if tx_id is None and idx is None:
            raise CommonException("Either 'tx_id' or 'idx' must be provided")

        if tx_id is not None and idx is not None:
            raise CommonException(
                "Both 'tx_id' and 'idx' cannot be accepted at the same time.",
            )

        return values

class RegisterModel(BaseModel):
    address: str
    btc_balance: BtcBalance

class WitnessData(BaseModel):
    amount_sat: int
    blinding: Optional[int]

class Recipient(BaseModel):
    """Recipient model for asset transfer."""
    recipient_id: str
    witness_data: Optional[WitnessData] = None
    amount: int
    transport_endpoints: List[str]
    
class SendAssetBeginRequestModel(BaseModel):
    invoice: str | None = None
    asset_id: str| None = None
    recipient_id: str= None
    amount: int= None

class SendAssetBeginModel(BaseModel):
    recipient_map: dict[str, List[Recipient]]
    donation: bool = False
    fee_rate: int = 1
    min_confirmations: int = 1

class Media(BaseModel):
    """Model for list asset"""
    file_path: str
    digest: str
    hex: str | None = None
    mime: str


class Balance(BaseModel):
    """Model for list asset"""
    settled: int
    future: int
    spendable: int


class Token(BaseModel):
    """Model for list asset"""
    index: int
    ticker: str | None = None
    name: str | None = None
    details: str | None = None
    embedded_media: bool
    media: Media
    attachments: dict[str, Media]
    reserves: bool

class Outpoint(BaseModel):
    txid: str
    vout: int
class Backup(BaseModel):
    password: str

class RgbAllocation(BaseModel):
    asset_id: Optional[str]
    amount: int
    settled: bool

class Utxo(BaseModel):
    outpoint: Outpoint
    btc_amount: int
    colorable: bool
    exists: bool

class Unspent(BaseModel):
    utxo: Utxo
    rgb_allocations: List[RgbAllocation]

class Balance(BaseModel):
    settled: int
    future: int
    spendable: int

class ReceiveData(BaseModel):
    invoice: str
    recipient_id: str
    expiration_timestamp: Optional[int]
    batch_transfer_idx: int

class SendResult(BaseModel):
    txid: str
    batch_transfer_idx: int

class BtcBalance(BaseModel):
    vanilla: Balance
    colored: Balance

class AssetIface(enum.IntEnum):
    RGB20 = 0
    
    RGB21 = 1
    
    RGB25 = 2

class AssetNia(BaseModel):
    asset_id: str
    asset_iface: AssetIface
    ticker: str
    name: str
    details: Optional[str]
    precision: int
    issued_supply: int
    timestamp: int
    added_at: int
    balance: Balance
    media: Optional[Media]

class AssetModel(BaseModel):
    """Model for asset """
    asset_id: str
    asset_iface: str
    ticker: str | None = None
    name: str
    details: str | None
    precision: int
    issued_supply: int
    timestamp: int
    added_at: int
    balance: AssetBalanceResponseModel
    media: Media | None = None
    token: Token | None = None


class TransportEndpoint(BaseModel):
    """Model representing transport endpoints."""

    endpoint: str
    transport_type: str
    used: bool

# -------------------- Request models -----------------------


class AssetIdModel(BaseModel):
    """Request model for asset balance."""

    asset_id: str


class CreateUtxosRequestModel(BaseModel):
    """Request model for creating UTXOs."""

    up_to: bool | None = False
    num: int = NO_OF_UTXO
    size: int = UTXO_SIZE_SAT
    fee_rate: int = FEE_RATE_FOR_CREATE_UTXOS
    skip_sync: bool = False


class DecodeRgbInvoiceRequestModel(BaseModel):
    """Request model for decoding RGB invoices."""

    invoice: str


class IssueAssetNiaRequestModel(BaseModel):
    """Request model for issuing assets nia."""
    amounts: list[int]
    ticker: str
    name: str
    precision: int = 0


class IssueAssetCfaRequestModelWithDigest(IssueAssetNiaRequestModel):
    """Request model for issuing assets."""
    file_digest: str


class IssueAssetCfaRequestModel(IssueAssetNiaRequestModel):
    """Request model for issuing assets."""
    file_path: str


class IssueAssetUdaRequestModel(IssueAssetCfaRequestModel):
    """Request model for issuing assets."""
    attachments_file_paths: list[list[str]]


class RefreshRequestModel(BaseModel):
    """Request model for refresh wallet"""
    skip_sync: bool = False


class RgbInvoiceRequestModel(BaseModel):
    """Request model for RGB invoices."""

    min_confirmations: int = 1
    asset_id: str | None = None
    amount: int | None = None
    duration_seconds: int = RGB_INVOICE_DURATION_SECONDS


class SendAssetRequestModel(BaseModel):
    """Request model for sending assets."""

    asset_id: str
    amount: int
    recipient_id: str
    donation: bool | None = False
    fee_rate: int
    min_confirmations: int
    transport_endpoints: list[str]
    skip_sync: bool = False


class ListTransfersRequestModel(AssetIdModel):
    """Request model for listing asset transfers."""



class GetAssetMediaModelRequestModel(BaseModel):
    """Response model for get asset medial api"""
    digest: str


class FailTransferRequestModel(BaseModel):
    """Response model for fail transfer"""
    batch_transfer_idx: int
    no_asset_only: bool = False
    skip_sync: bool = False

# -------------------- Response models -----------------------


class AssetBalanceResponseModel(Balance):
    """Response model for asset balance."""
    offchain_outbound: int = 0
    offchain_inbound: int = 0


class CreateUtxosResponseModel(StatusModel):
    """Response model for creating UTXOs."""


class DecodeRgbInvoiceResponseModel(BaseModel):
    """Response model for decoding RGB invoices."""

    recipient_id: str
    asset_iface: str | None = None
    asset_id: str | None = None
    amount: str | None = None
    network: str
    expiration_timestamp: int
    transport_endpoints: list[str]


class GetAssetResponseModel(BaseModel):
    """Response model for list assets."""
    nia: list[AssetModel | None] | None = []
    uda: list[AssetModel | None] | None = []
    cfa: list[AssetModel | None] | None = []


class IssueAssetResponseModel(AssetModel):
    """Response model for issuing assets."""


class ListTransferAssetResponseModel(BaseModel):
    """Response model for listing asset transfers."""

    transfers: list[TransferAsset | None] | None = []


class ListTransferAssetWithBalanceResponseModel(ListTransferAssetResponseModel):
    """Response model for listing asset transfers with asset balance"""
    asset_balance: AssetBalanceResponseModel

class RefreshTransferResponseModel(StatusModel):
    """Response model for refreshing asset transfers."""


class RgbInvoiceDataResponseModel(BaseModel):
    """Response model for invoice data."""

    recipient_id: str
    invoice: str
    expiration_timestamp: datetime
    batch_transfer_idx: int


class SendAssetResponseModel(BaseModel):
    """Response model for sending assets."""

    txid: str


class GetAssetMediaModelResponseModel(BaseModel):
    """Response model for get asset media api"""
    bytes_hex: str


class PostAssetMediaModelResponseModel(BaseModel):
    """Response model for get asset media api"""
    digest: str


class RgbAssetPageLoadModel(BaseModel):
    """RGB asset detail page load model"""
    asset_id: str | None = None
    asset_name: str | None = None
    image_path: str | None = None
    asset_type: str


class FailTransferResponseModel(BaseModel):
    """Response model for fail transfer"""
    transfers_changed: bool

class TransferTransportEndpoint(BaseModel):
    endpoint: str
    transport_type: TransportType
    used: bool

class Transfer(BaseModel):
    """Model representing a transfer."""

    idx: int
    batch_transfer_idx: int
    created_at: int
    updated_at: int
    status: TransferStatus
    amount: int
    kind: TransferKind
    txid: Optional[str]
    recipient_id: Optional[str]
    receive_utxo: Optional[Outpoint]
    change_utxo: Optional[Outpoint]
    expiration: Optional[int]
    transport_endpoints: List[TransferTransportEndpoint]