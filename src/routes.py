from typing import List, Optional
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.dependencies import get_wallet,create_wallet
from rgb_lib import BitcoinNetwork, Wallet,AssetSchema
from src.rgb_model import AssetNia, Backup, Balance, BtcBalance, DecodeRgbInvoiceRequestModel, DecodeRgbInvoiceResponseModel, FailTransferRequestModel, GetAssetResponseModel, IssueAssetNiaRequestModel, ListTransfersRequestModel, ReceiveData, Recipient, RefreshRequestModel, RegisterModel, RgbInvoiceRequestModel, SendAssetBeginModel, SendAssetBeginRequestModel, SendResult, Transfer, Unspent
from fastapi import APIRouter, Depends
import os
from src.wallet_utils import BACKUP_PATH, create_wallet_instance, get_backup_path, remove_backup_if_exists, restore_wallet_instance, test_wallet_instance
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
    upTo: bool = False
    num: int = 5
    size: int = 32500
    feeRate: int = 5



class SendAssetEndRequestModel(BaseModel):
    signed_psbt: str

class CreateUtxosEnd(BaseModel):
    signedPsbt: str

class AssetBalanceRequest(BaseModel):
    assetId: str

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

@router.post("/wallet/listunspents",response_model=List[Unspent])
def list_unspents(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    unspents = wallet.list_unspents(online, False, False)
    return unspents

@router.post("/wallet/createutxosbegin",response_model=str)
def create_utxos_begin(req: CreateUtxosBegin, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    psbt = wallet.create_utxos_begin(online, req.upTo, req.num, req.size, req.feeRate, False)
    return psbt

@router.post("/wallet/createutxosend",response_model=int)
def create_utxos_end(req: CreateUtxosEnd, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.create_utxos_end(online, req.signedPsbt, False)
    return result

@router.post("/wallet/listassets",response_model=GetAssetResponseModel)
def list_assets(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    wallet.sync(online)
    assets = wallet.list_assets([AssetSchema.NIA])
    return assets

@router.post("/wallet/btcbalance",response_model=BtcBalance)
def get_btc_balance(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    btc_balance = wallet.get_btc_balance(online, False)
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

@router.post("/wallet/assetbalance",response_model=Balance)
def get_asset_balance(req: AssetBalanceRequest, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, _,xpub_van, xpub_col = wallet_dep
    balance = wallet.get_asset_balance(req.assetId)
    return balance
# ,response_model=DecodeRgbInvoiceResponseModel
@router.post("/wallet/decodergbinvoice")
def decode_rgb_invoice(req:DecodeRgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet) ):
    wallet, online,xpub_van, xpub_col = wallet_dep
    invoice_data = rgb_lib.Invoice(req.invoice).invoice_data()
    print("invoice data", invoice_data)
    return invoice_data

@router.post("/wallet/sendbegin")
def send_begin(req: SendAssetBeginRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    invoice_data = rgb_lib.Invoice(req.invoice).invoice_data()
    print("request data",xpub_van, req.asset_id, req.amount)
    print("invoice data", invoice_data)

    resolved_amount = invoice_data.amount if invoice_data.amount is not None else req.amount
    if resolved_amount is None:
        raise HTTPException(status_code=400, detail="Amount is required")

    recipient_map = {
        invoice_data.asset_id or req.asset_id: [
            Recipient(
                recipient_id=invoice_data.recipient_id,
                amount=resolved_amount,
                transport_endpoints=invoice_data.transport_endpoints
            )
        ]
    }
    print("invoice data", recipient_map)
    send_model = SendAssetBeginModel(
        recipient_map=recipient_map,
        donation=True,
        fee_rate=5,
        min_confirmations=1
    )
    
    psbt = wallet.send_begin(online, send_model.recipient_map, send_model.donation, send_model.fee_rate, send_model.min_confirmations)
    return psbt

class SignPSBT(BaseModel):
    mnemonic: str
    psbt: str
    xpub_van: str
    xpub_col: str

@router.post("/wallet/sign")
def sign_psbt(req:SignPSBT):
    wallet,online = test_wallet_instance(req.xpub_van,req.xpub_col, req.mnemonic)
    print("signing psbt",req.psbt)
    signed_psbt = wallet.sign_psbt(req.psbt)

    print("signed_psbt", signed_psbt)
    return signed_psbt

@router.post("/wallet/sendend", response_model=SendResult)
def send_begin(req: SendAssetEndRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.send_end(online, req.signed_psbt, False)
    return result

@router.post("/blindreceive", response_model=ReceiveData)
def generate_invoice(req: RgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    receive = wallet.blind_receive(req.asset_id, req.amount, 900, [PROXY_URL], 1)
    return receive

@router.post("/wallet/failtransfers")
def failtransfers(req: FailTransferRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    print("Failing transfers",req.batch_transfer_idx)
    failed = wallet.fail_transfers(online, req.batch_transfer_idx, req.no_asset_only, req.skip_sync)
    print("Failing res",failed)
    return {'failed': failed}

@router.post("/wallet/listtransactions")
def list_transaction(wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online ,xpub_van, xpub_col= wallet_dep
    list_transactions = wallet.list_transactions(online, False)
    return list_transactions

@router.post("/wallet/listtransfers",response_model=List[Transfer])
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
):
    remove_backup_if_exists(xpub_van)
    backup_path = get_backup_path(xpub_van)
    with open(backup_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        # Restore wallet from backup
        restore_wallet_instance(xpub_van, password, backup_path)
        return {"message": "Wallet restored successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to restore wallet: {str(e)}")