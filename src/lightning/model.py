"""Module containing models related to Lightning API."""
from typing import Literal, Optional
from pydantic import BaseModel


class LightningAsset(BaseModel):
    """Model for Lightning asset payment details."""
    asset_id: str
    amount: int  # Using int instead of bigint for JSON compatibility


class PayLightningInvoiceRequestModel(BaseModel):
    """Request model for paying a Lightning invoice."""
    invoice: str
    max_fee_sats: int = 3000


class LightningSendRequest(BaseModel):
    """Response model for Lightning send request."""
    id: str
    status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    payment_type: Literal["BTC", "ASSET"]
    amount_sats: Optional[int] = None
    asset: Optional[LightningAsset] = None
    fee_sats: Optional[int] = None
    created_at: str


class GetLightningSendFeeEstimateRequestModel(BaseModel):
    """Request model for Lightning fee estimate."""
    invoice: str
    asset: Optional[LightningAsset] = None


class CreateLightningInvoiceRequestModel(BaseModel):
    """Request model for creating a Lightning invoice."""
    amount_sats: Optional[int] = None
    asset: Optional[LightningAsset] = None
    expiry_seconds: Optional[int] = None


class LightningReceiveRequest(BaseModel):
    """Response model for Lightning receive request."""
    id: str
    invoice: str
    status: Literal["OPEN", "SETTLED", "EXPIRED", "FAILED"]
    payment_type: Literal["BTC", "ASSET"]
    amount_sats: Optional[int] = None
    asset: Optional[LightningAsset] = None
    created_at: str


class ListPaymentsResponse(BaseModel):
    """Response model for listing payments."""
    sent: list[LightningSendRequest]
    received: list[LightningReceiveRequest]

