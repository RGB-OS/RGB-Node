from typing import List, Optional
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.dependencies import get_wallet,create_wallet
from rgb_lib import BitcoinNetwork, Wallet,AssetSchema, Assignment
from src.rgb_model import AssetIfa, AssetNia, Backup, Balance, BtcBalance, DecodeRgbInvoiceRequestModel, DecodeRgbInvoiceResponseModel, FailTransferRequestModel, GetAssetResponseModel, GetFeeEstimateRequestModel, InflateAssetIfaRequestModel, InflateEndRequestModel, IssueAssetIfaRequestModel, IssueAssetNiaRequestModel, ListTransfersRequestModel, OperationResult, ReceiveData, Recipient, RefreshRequestModel, RegisterModel, RgbInvoiceRequestModel, SendAssetBeginModel, SendAssetBeginRequestModel, SendBtcBeginRequestModel, SendBtcEndRequestModel, SendResult, Transfer, Unspent
from fastapi import APIRouter, Depends
import os
from src.wallet_utils import BACKUP_PATH, create_wallet_instance, get_backup_path, remove_backup_if_exists, restore_wallet_instance, test_wallet_instance, WalletStateExistsError
import shutil
import uuid
import rgb_lib

env_network = int(os.getenv("NETWORK", "3"))
NETWORK = BitcoinNetwork(env_network)

router = APIRouter()
invoices = {}
PROXY_URL = os.getenv('PROXY_ENDPOINT')
vanilla_keychain = 1

class WatchOnly(BaseModel):
    xpub: str

class CreateUtxosBegin(BaseModel):
    mnemonic: str = None
    up_to: bool = False
    num: int = 5
    size: int = 1000
    fee_rate: int = 5



class SendAssetEndRequestModel(BaseModel):
    signed_psbt: str

class CreateUtxosEnd(BaseModel):
    signed_psbt: str

class AssetBalanceRequest(BaseModel):
    asset_id: str

@router.post("/wallet/generate_keys")
def register_wallet():
    send_keys = rgb_lib.generate_keys(NETWORK)
    return send_keys

@router.post("/wallet/register", response_model=RegisterModel)
def register_wallet(wallet_dep: tuple[Wallet, object,str,str]=Depends(create_wallet)):
    wallet, online ,xpub_van, xpub_col= wallet_dep
    btc_balance = wallet.get_btc_balance(online, False)
    address = wallet.get_address()
    return { "address": address, "btc_balance": btc_balance }
@router.post("/wallet/get_fee_estimation")
def get_fee_estimation(req:GetFeeEstimateRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    # fee_estimation = wallet.get_fee_estimation(online,req.blocks)
    # return fee_estimation
    return 5
@router.post("/wallet/sendbtcbegin")
def send_btc_begin(req: SendBtcBeginRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    psbt = wallet.send_btc_begin(online, req.address, req.amount, req.fee_rate, req.skip_sync)
    return psbt
@router.post("/wallet/sendbtcend")
def send_btc_end(req: SendBtcEndRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.send_btc_end(online, req.signed_psbt, req.skip_sync)
    return result
# response_model=List[Unspent]
@router.post("/wallet/listunspents")
def list_unspents(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    unspents = wallet.list_unspents(online, False, False)
    return unspents

@router.post("/wallet/createutxosbegin",response_model=str)
def create_utxos_begin(req: CreateUtxosBegin, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    psbt = wallet.create_utxos_begin(online, req.up_to, req.num, req.size, req.fee_rate, False)
    return psbt

@router.post("/wallet/createutxosend",response_model=int)
def create_utxos_end(req: CreateUtxosEnd, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.create_utxos_end(online, req.signed_psbt, False)
    return result

@router.post("/wallet/listassets",response_model=GetAssetResponseModel)
def list_assets(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    assets = wallet.list_assets([AssetSchema.NIA,AssetSchema.IFA])
    return assets

@router.post("/wallet/btcbalance",response_model=BtcBalance)
def get_btc_balance(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    print("Getting BTC balance...")
    print(xpub_van, xpub_col)
    btc_balance = wallet.get_btc_balance(online, True)
    return btc_balance

@router.post("/wallet/address",response_model=str)
def get_address(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet,online, xpub_van, xpub_col= wallet_dep
    address = wallet.get_address()
    return address

@router.post("/wallet/issueassetnia",response_model=AssetNia)
def issue_asset_nia(req: IssueAssetNiaRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    asset = wallet.issue_asset_nia(req.ticker, req.name, req.precision, req.amounts)
    return asset

@router.post("/wallet/issueassetifa",response_model=AssetIfa)
def issue_asset_cfa(req: IssueAssetIfaRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    asset = wallet.issue_asset_ifa(req.ticker, req.name, req.precision, req.amounts, req.inflation_amounts, req.replace_rights_num, req.reject_list_url)
    return asset

@router.post('/wallet/inflatebegin',response_model=str)
def inflate_begin(req: InflateAssetIfaRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    psbt = wallet.inflate_begin(online,req.asset_id, req.inflation_amounts,req.fee_rate,req.min_confirmations)
    return psbt

@router.post('/wallet/inflateend',response_model=OperationResult)
def inflate_end(req: InflateEndRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.inflate_end(online,req.signed_psbt)
    return result

@router.post("/wallet/assetbalance",response_model=Balance)
def get_asset_balance(req: AssetBalanceRequest, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, _,xpub_van, xpub_col = wallet_dep
    balance = wallet.get_asset_balance(req.asset_id)
    return balance

@router.post("/wallet/decodergbinvoice")
def decode_rgb_invoice(req:DecodeRgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet) ):
    wallet, online,xpub_van, xpub_col = wallet_dep
    invoice_data = rgb_lib.Invoice(req.invoice).invoice_data()
    return invoice_data


@router.post("/wallet/sendbegin")
def send_begin(req: SendAssetBeginRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    invoice_data = rgb_lib.Invoice(req.invoice).invoice_data()
    resolved_amount = Assignment.FUNGIBLE(req.amount)
    if resolved_amount is None:
        raise HTTPException(status_code=400, detail="Amount is required")
    if not (invoice_data.asset_id or req.asset_id):
        raise HTTPException(status_code=400, detail="Missing asset_id: must be provided in invoice or request")
    # Check if recipient_id contains "wvout:" to determine if it's a witness send
    is_witness_send = "wvout:" in (invoice_data.recipient_id)
    # Set witness_data based on whether it's a witness send
    if is_witness_send:
        if req.witness_data is None:
            raise HTTPException(status_code=400, detail="witness_data is required for witness sends")
        # Validate witness_data for witness sends
        if not isinstance(req.witness_data.amount_sat, int):
            raise HTTPException(status_code=400, detail="witness_data.amount_sat must be a number")
        if req.witness_data.amount_sat <= 0:
            raise HTTPException(status_code=400, detail="witness_data.amount_sat must be a positive number")
        witness_data = rgb_lib.WitnessData(amount_sat=req.witness_data.amount_sat, blinding=req.witness_data.blinding)
    else:
        # For non-witness sends, witness_data is not required and should be None
        witness_data = None

    recipient_map = {
        invoice_data.asset_id or req.asset_id: [
            Recipient(
                recipient_id=invoice_data.recipient_id,
                assignment=resolved_amount,
                witness_data=witness_data,
                transport_endpoints=invoice_data.transport_endpoints
            )
        ]
    }
   
    send_model = SendAssetBeginModel(
        recipient_map=recipient_map,
        donation=False,
        fee_rate=req.fee_rate or 5,
        min_confirmations=req.min_confirmations or 3
    )
    print("invoice data", recipient_map, send_model)
    
    psbt = wallet.send_begin(online, send_model.recipient_map, send_model.donation, send_model.fee_rate, send_model.min_confirmations)
    return psbt

class SignPSBT(BaseModel):
    mnemonic: str
    psbt: str
    xpub_van: str
    xpub_col: str
    master_fingerprint: str

@router.post("/wallet/sign")
def sign_psbt(req:SignPSBT):
    wallet,online = test_wallet_instance(req.xpub_van,req.xpub_col, req.mnemonic,req.master_fingerprint)
    signed_psbt = wallet.sign_psbt(req.psbt)

    print("signed_psbt", signed_psbt)
    return signed_psbt
@router.post("/wallet/sendend", response_model=SendResult)
def send_begin(req: SendAssetEndRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.send_end(online, req.signed_psbt, False)
    return result

@router.post("/wallet/blindreceive", response_model=ReceiveData)
def generate_invoice(req: RgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    assignment = Assignment.FUNGIBLE(req.amount)
    duration_seconds=1500
    receive = wallet.blind_receive(req.asset_id, assignment, duration_seconds, [PROXY_URL], 3)
    return receive

# old methot should be removed after prod update
@router.post("/blindreceive", response_model=ReceiveData)
def generate_invoice(req: RgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    assignment = Assignment.FUNGIBLE(req.amount)
    duration_seconds=1500
    receive = wallet.blind_receive(req.asset_id, assignment, duration_seconds, [PROXY_URL], 3)
    return receive

@router.post("/wallet/witnessreceive", response_model=ReceiveData)
def generate_invoice(req: RgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    assignment = Assignment.FUNGIBLE(req.amount)
    duration_seconds=1500
    receive = wallet.witness_receive(req.asset_id, assignment, duration_seconds, [PROXY_URL], 3)
    return receive

@router.post("/wallet/failtransfers")
def failtransfers(req: FailTransferRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    failed = wallet.fail_transfers(online, req.batch_transfer_idx, req.no_asset_only, req.skip_sync)
    return {'failed': failed}

@router.post("/wallet/listtransactions")
def list_transaction(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online ,xpub_van, xpub_col= wallet_dep
    list_transactions = wallet.list_transactions(online, False)
    return list_transactions

@router.post("/wallet/listtransfers")
def list_transfers(req:ListTransfersRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    
    list_transfers = wallet.list_transfers(req.asset_id)
    return list_transfers

@router.post("/wallet/refresh")
def refresh_wallet(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    refreshed_transfers = wallet.refresh(online,None, [], False)
    return refreshed_transfers

@router.post("/wallet/sync")
def wallet_sync(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    wallet.sync(online)
    return {"message": "Wallet synced successfully"}

@router.post("/wallet/backup")
def create_backup(req:Backup, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online, xpub_van, xpub_col = wallet_dep
    remove_backup_if_exists(xpub_van)
    backup_path = get_backup_path(xpub_van)
    wallet.backup(backup_path, req.password)

    if not os.path.exists(backup_path):
        raise HTTPException(status_code=500, detail="Backup file was not created")

    return {
        "message": "Backup created successfully",
        "download_url": f"/wallet/backup/{xpub_van}"
    }
@router.get("/wallet/backup/{backup_id}")
def get_backup(backup_id):
    backup_path = get_backup_path(backup_id)
    if not os.path.isfile(backup_path):
        raise HTTPException(status_code=404, detail="Backup file not found")
    
    return FileResponse(
        path=backup_path,
        media_type="application/octet-stream",
        filename=f"{backup_id}.backup"
    )
@router.post("/wallet/restore")
def restore_wallet(
    file: UploadFile = File(...),
    password: str = Form(...),
    xpub_van: str = Form(...),
    xpub_col: str = Form(...),
    master_fingerprint: str = Form(...)
):
    remove_backup_if_exists(xpub_van)
    backup_path = get_backup_path(xpub_van)
    print(backup_path)
    with open(backup_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        restore_wallet_instance(xpub_van,xpub_col,master_fingerprint, password, backup_path)
        return {"message": "Wallet restored successfully"}
    except WalletStateExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to restore wallet: {str(e)}")
