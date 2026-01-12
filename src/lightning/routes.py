"""Lightning API routes with mock implementations."""
from datetime import datetime
import os
import base64
from typing import Optional, Tuple
from fastapi import APIRouter, HTTPException, Depends
from rgb_lib import Assignment, Wallet
import rgb_lib
from src.rgb_model import Recipient, SendAssetBeginModel
from src.lightning.model import (
    PayLightningInvoiceRequestModel,
    LightningSendRequest,
    GetLightningSendFeeEstimateRequestModel,
    CreateLightningInvoiceRequestModel,
    LightningReceiveRequest,
    LightningAsset,
    ListPaymentsResponse,
)
from src.routes import SendAssetEndRequestModel
from src.rln_client import get_rln_client
from src.dependencies import get_wallet
import uuid 

router = APIRouter(prefix="/lightning", tags=["Lightning"])

# Mock storage for Lightning requests
lightning_send_requests: dict[str, LightningSendRequest] = {}
lightning_receive_requests: dict[str, LightningReceiveRequest] = {}
# Map PSBT to original invoice for pay-invoice flow
psbt_to_invoice_map: dict[str, str] = {}


@router.post("/pay-invoice-begin", response_model=str)
async def pay_lightning_invoice_begin(
    req: PayLightningInvoiceRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> str:
    """
    Begins a Lightning invoice payment process.
    
    Returns the invoice string as a mock PSBT (later will be constructed base64 PSBT).
    """
    wallet, online,xpub_van, xpub_col = wallet_dep
    rln = get_rln_client()
    asset_id = os.getenv("RLN_ASSET_ID")
    test_invoice = os.getenv("RLN_TEST_INVOICE")
    ln_invoice_data = await rln.decode_lightning_invoice(req.invoice)
    invoice_data = rgb_lib.Invoice(test_invoice).invoice_data()
    asset_amount = ln_invoice_data.get("asset_amount")
    assignment = Assignment.FUNGIBLE(asset_amount if asset_amount is not None else 10)
    recipient_map = {
        asset_id: [
            Recipient(
                recipient_id=invoice_data.recipient_id,
                assignment=assignment,
                witness_data=None,
                transport_endpoints=invoice_data.transport_endpoints
            )
        ]
    }
   
    send_model = SendAssetBeginModel(
        recipient_map=recipient_map,
        donation=False,
        fee_rate=5,
        min_confirmations=3
    )

    psbt = wallet.send_begin(online, send_model.recipient_map, send_model.donation, send_model.fee_rate, send_model.min_confirmations)
    
    # Map the PSBT to the invoice to use in pay-invoice-end
    psbt_to_invoice_map[xpub_van] = req.invoice
    
    return psbt


@router.post("/pay-invoice-end")
async def pay_lightning_invoice_end(
    req: SendAssetEndRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
):
    """
    Completes a Lightning invoice payment using signed PSBT.
    
    Works the same as pay-invoice but uses signed_psbt instead of invoice.
    """
    wallet, online, xpub_van, xpub_col = wallet_dep
    
   
    wallet.finalize_psbt(req.signed_psbt)
    
    invoice_to_use = psbt_to_invoice_map.get(xpub_van)
    
    if not invoice_to_use:
        raise HTTPException(
            status_code=400,
            detail="No invoice found. Please call /pay-invoice-begin first to create a PSBT."
        )
    

    rln = get_rln_client()
    
    invoice_data = await rln.decode_lightning_invoice(invoice_to_use)
    
    payment_response = await rln.send_payment(invoice_to_use)
    
    payment_hash = payment_response["payment_hash"]
    rln_status = payment_response["status"]
    
    status_mapping = {
        "Pending": "PENDING",
        "Succeeded": "SUCCEEDED",
        "Failed": "FAILED"
    }
    
    mapped_status = status_mapping.get(rln_status, "PENDING")
    
    amt_msat = invoice_data.get("amt_msat", 0)
    amount_sats = amt_msat // 1000 if amt_msat else None
    
    asset_id = invoice_data.get("asset_id")
    asset_amount = invoice_data.get("asset_amount")
    
    payment_type = "ASSET" if asset_id and asset_amount else "BTC"
    
    asset = None
    if payment_type == "ASSET" and asset_id and asset_amount:
        asset = LightningAsset(asset_id=asset_id, amount=asset_amount)
    
    send_request = LightningSendRequest(
        id=payment_hash,
        status=mapped_status,
        payment_type=payment_type,
        amount_sats=amount_sats if asset is None else None,
        asset=asset,
        fee_sats=None,
        created_at=datetime.utcnow().isoformat() + "Z"
    )
    
    lightning_send_requests[payment_hash] = send_request
    
    psbt_to_invoice_map.pop(xpub_van, None)
    
    return send_request


@router.get("/send-request/{request_id}", response_model=Optional[LightningSendRequest])
async def get_lightning_send_request(
    request_id: str,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> Optional[LightningSendRequest]:
    """
    Returns the current status of a Lightning payment initiated with payLightningInvoice.
    
    Works for both BTC and asset payments.
    """
    rln = get_rln_client()
    
    try:
        payment_data = await rln.get_payment(request_id)
        payment = payment_data.get("payment")
        
        if not payment:
            return None
        
        rln_status = payment.get("status", "")
        status_mapping = {
            "Succeeded": "SUCCEEDED",
            "Pending": "PENDING",
            "Failed": "FAILED"
        }
        mapped_status = status_mapping.get(rln_status, "PENDING")
        
        amt_msat = payment.get("amt_msat", 0)
        amount_sats = amt_msat // 1000 if amt_msat else None
        
        asset_id = payment.get("asset_id")
        asset_amount = payment.get("asset_amount")
        payment_type = "ASSET" if asset_id and asset_amount else "BTC"
        
        asset = None
        if payment_type == "ASSET" and asset_id and asset_amount:
            asset = LightningAsset(asset_id=asset_id, amount=asset_amount)
        
        created_at_timestamp = payment.get("created_at", 0)
        if created_at_timestamp:
            created_at = datetime.utcfromtimestamp(created_at_timestamp).isoformat() + "Z"
        else:
            created_at = datetime.utcnow().isoformat() + "Z"
        
        return LightningSendRequest(
            id=payment.get("payment_hash", request_id),
            status=mapped_status,
            payment_type=payment_type,
            amount_sats=amount_sats if asset is None else None,
            asset=asset,
            fee_sats=None,
            created_at=created_at
        )
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise
    except Exception as e:
        return None


@router.post("/fee-estimate", response_model=int)
async def get_lightning_send_fee_estimate(
    req: GetLightningSendFeeEstimateRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> int:
    """
    Estimates the routing fee required to pay a Lightning invoice.
    
    For asset payments, the returned fee is always denominated in satoshis.
    """
    return 10


@router.post("/create-invoice", response_model=LightningReceiveRequest)
async def create_lightning_invoice(
    req: CreateLightningInvoiceRequestModel,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> LightningReceiveRequest:
    """
    Creates a Lightning invoice for receiving BTC or asset payments.
    """
    if req.asset is None and req.amount_sats is None:
        raise HTTPException(
            status_code=400,
            detail="amount_sats is required for BTC invoices"
        )
    
    rln = get_rln_client()
    
    payment_type = "ASSET" if req.asset else "BTC"
    
    if payment_type == "ASSET" and req.amount_sats is None:
        amount_sats = 3000
    else:
        amount_sats = req.amount_sats
    
    amt_msat = amount_sats * 1000
    
    expiry_sec = req.expiry_seconds or 420

    invoice = await rln.create_lightning_invoice(
        amt_msat=amt_msat,
        expiry_sec=expiry_sec,
        asset_id=req.asset.asset_id if req.asset else None,
        asset_amount=req.asset.amount if req.asset else None
    )
    
    request_id = str(uuid.uuid4())
    
    receive_request = LightningReceiveRequest(
        id=request_id,
        invoice=invoice,
        status="OPEN",
        payment_type=payment_type,
        amount_sats=amount_sats,
        asset=req.asset,
        created_at=datetime.utcnow().isoformat() + "Z"
    )
    
    lightning_receive_requests[request_id] = receive_request
    
    return receive_request


@router.get("/receive-request/{request_id}", response_model=Optional[LightningReceiveRequest])
async def get_lightning_receive_request(
    request_id: str,
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
) -> Optional[LightningReceiveRequest]:
    """
    Returns the status of a Lightning invoice created with createLightningInvoice.
    
    Supports both BTC and asset invoices.
    """
    receive_request = lightning_receive_requests.get(request_id)
    if not receive_request:
        return None
    
    rln = get_rln_client()
    rln_status = await rln.get_invoice_status(receive_request.invoice)
    
    status_mapping = {
        "Pending": "OPEN",
        "Succeeded": "SETTLED",
        "Failed": "FAILED",
        "Expired": "EXPIRED"
    }
    
    mapped_status = status_mapping.get(rln_status, "OPEN")
    
    updated_request = LightningReceiveRequest(
        id=receive_request.id,
        invoice=receive_request.invoice,
        status=mapped_status,
        payment_type=receive_request.payment_type,
        amount_sats=receive_request.amount_sats,
        asset=receive_request.asset,
        created_at=receive_request.created_at
    )
    
    lightning_receive_requests[request_id] = updated_request
    
    return updated_request


@router.get("/listpayments")
async def list_payments(
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
):
    """
    Lists all Lightning payments from the RLN node.
    
    Returns the same data structure as the RLN node's listpayments endpoint.
    """
    rln = get_rln_client()
    return await rln.list_payments()


@router.get("/listtransactions")
async def list_transactions(
    wallet_dep: Tuple[Wallet, object, str, str] = Depends(get_wallet)
):
    """
    Lists all transactions from the RLN node.
    
    Returns the same data structure as the RLN node's listtransactions endpoint.
    """
    rln = get_rln_client()
    return await rln.list_transactions(skip_sync=False)


def mock_invoice_suffix() -> str:
    """Generate a mock invoice suffix for testing."""
    return str(uuid.uuid4()).replace("-", "")[:32]

