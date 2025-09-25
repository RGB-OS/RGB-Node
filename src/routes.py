from typing import List, Optional
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.dependencies import get_wallet,create_wallet
from rgb_lib import BitcoinNetwork, Wallet,AssetSchema, Assignment
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
    size: int = 1000
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
# response_model=List[Unspent]
@router.post("/wallet/listunspents")
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
 
    resolved_amount = Assignment.FUNGIBLE(req.amount)
    if resolved_amount is None:
        raise HTTPException(status_code=400, detail="Amount is required")

    recipient_map = {
        invoice_data.asset_id or req.asset_id: [
            Recipient(
                recipient_id=invoice_data.recipient_id,
                assignment=resolved_amount,
                transport_endpoints=invoice_data.transport_endpoints
            )
        ]
    }
    print("invoice data", recipient_map)
    send_model = SendAssetBeginModel(
        recipient_map=recipient_map,
        donation=False,
        fee_rate=5,
        min_confirmations=3
    )
    
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
    print("signing psbt",req.psbt)
    signed_psbt = wallet.sign_psbt(req.psbt)

    print("signed_psbt", signed_psbt)
    return signed_psbt
# {
#       "mnemonic": "input asset pistol aware deliver imitate sausage behave news category manual catch",
#     "xpub": "tpubD6NzVbkrYhZ4XSMh32ufPtwNcCEXR2UPtWPKH6cr2sW4GckunPiZt3Kt1Nn8ssYPSyfaEXMHKBTgRomEe2ZiCbeevAGBBkQMmRDca8DYxhb",
#     "xpub_van": "tpubDC3SyMdeKCosZC2J2mk72m4Xp5mikH9VzTh6sVejVww3LS19HPrtLmcoyEQrbzxRcQtPQntDg5vkXuuah7QLhLKsvEvUU4B7QioM7Xc5D8K",
#     "xpub_col": "tpubDCW9yjx496cAwMCKSEtgnsrYgJBzZgvzzcvKsvitJTugdzF4FM3YUpKwZZ6P2L9XDhNtbHLyH7PvRN7GumcubAqyQQ3dctjaATVJaqajxa3",
#     "master_fingerprint": "cf01173d",
#     "psbt":"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"
# }
@router.post("/wallet/sendend", response_model=SendResult)
def send_begin(req: SendAssetEndRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    result = wallet.send_end(online, req.signed_psbt, False)
    return result

@router.post("/blindreceive", response_model=ReceiveData)
def generate_invoice(req: RgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object,str,str]=Depends(get_wallet)):
    wallet, online,xpub_van, xpub_col = wallet_dep
    assignment = Assignment.FUNGIBLE(req.amount)
    print("signed_psbt", assignment)
    duration_seconds=900
    receive = wallet.blind_receive(req.asset_id, assignment, duration_seconds, [PROXY_URL], 3)
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
    with open(backup_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        # Restore wallet from backup
        restore_wallet_instance(xpub_van,xpub_col,master_fingerprint, password, backup_path)
        return {"message": "Wallet restored successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to restore wallet: {str(e)}")
