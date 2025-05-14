from typing import List, Optional
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.dependencies import get_wallet,create_wallet
from rgb_lib import BitcoinNetwork, Wallet,AssetSchema
from src.rgb_model import AssetNia, Backup, Balance, BtcBalance, FailTransferRequestModel, IssueAssetNiaRequestModel, ListTransfersRequestModel, ReceiveData, RefreshRequestModel, RegisterModel, RgbInvoiceRequestModel, SendResult, Transfer, Unspent
from fastapi import APIRouter, Depends
import os
from src.wallet_utils import BACKUP_PATH, get_backup_path, remove_backup_if_exists, restore_wallet_instance
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
    feeRate: int = 1

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
    recipient_map: dict[str, List[Recipient]]
    donation: bool = False
    fee_rate: int = 1
    min_confirmations: int = 1

class SendAssetEndRequestModel(BaseModel):
    signed_psbt: str

class CreateUtxosEnd(BaseModel):
    signedPsbt: str
class AssetBalanceRequest(BaseModel):
    xpub: str
    assetId: str
class InvoiceRequest(BaseModel):
    xpub: str
    assetId: str
    amount: int

@router.post("/wallet/register", response_model=RegisterModel)
def register_wallet(wallet_dep: tuple[Wallet, object]=Depends(create_wallet)):
    wallet, online = wallet_dep
    btc_balance = wallet.get_btc_balance(online, False)
    address = wallet.get_address()
    return { "address": address, "btc_balance": btc_balance }

@router.post("/wallet/listunspents",response_model=List[Unspent])
def list_unspents(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    unspents = wallet.list_unspents(online, False, False)
    return unspents

@router.post("/wallet/createutxosbegin",response_model=str)
def create_utxos_begin(req: CreateUtxosBegin, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    psbt = wallet.create_utxos_begin(online, req.upTo, req.num, req.size, req.feeRate, False)
    return psbt

@router.post("/wallet/createutxosend",response_model=int)
def create_utxos_end(req: CreateUtxosEnd, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    result = wallet.create_utxos_end(online, req.signedPsbt, False)
    return result

@router.post("/wallet/listassets",response_model=List[AssetSchema])
def list_assets(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    wallet.sync(online)
    assets = wallet.list_assets([AssetSchema.NIA])
    return assets

@router.post("/wallet/btcbalance",response_model=BtcBalance)
def get_btc_balance(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    btc_balance = wallet.get_btc_balance(online, False)
    return btc_balance

@router.post("/wallet/address",response_model=str)
def get_address(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    address = wallet.get_address()
    return address

@router.post("/wallet/issueassetnia",response_model=AssetNia)
def issue_asset_nia(req: IssueAssetNiaRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    asset = wallet.issue_asset_nia(online, req.amounts, req.ticker, req.name, req.precision, False)
    return asset

@router.post("/wallet/assetbalance",response_model=Balance)
def get_asset_balance(req: AssetBalanceRequest, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, _ = wallet_dep
    balance = wallet.get_asset_balance(req.assetId)
    return balance

@router.post("/wallet/sendbegin", response_model=str)
def send_begin(req: SendAssetBeginRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    psbt = wallet.send_begin(online, req.recipient_map, req.donation, req.fee_rate, req.min_confirmations)
    return psbt

@router.post("/wallet/sendend", response_model=SendResult)
def send_begin(req: SendAssetEndRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    result = wallet.send_end(online, req.signed_psbt, False)
    return result

@router.post("/blindreceive", response_model=ReceiveData)
def generate_invoice(req: RgbInvoiceRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    receive = wallet.blind_receive(req.asset_id, req.amount, 3600, [PROXY_URL], 1)
    return receive

@router.post("/wallet/failtransfers")
def failtransfers(req: FailTransferRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    print("Failing transfers",req.batch_transfer_idx)
    failed = wallet.fail_transfers(online, req.batch_transfer_idx, req.no_asset_only, req.skip_sync)
    # receive = wallet.blind_receive(req.asset_id, req.amount, None, ["rpc://regtest.thunderstack.org:3000/json-rpc"], 1)
    # receive = wallet.witness_receive(req.asset_id, req.amount, None, ["rpc://regtest.thunderstack.org:3000/json-rpc"], 1)
    print("Failing res",failed)
    return {'failed': failed}

@router.post("/wallet/listtransactions")
def list_transaction(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    list_transactions = wallet.list_transactions(online, False)
    return list_transactions

@router.post("/wallet/listtransfers",response_model=List[Transfer])
def list_transfers(req:ListTransfersRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    list_transfers = wallet.list_transfers(req.asset_id)
    return list_transfers

@router.post("/wallet/refresh")
def refresh_wallet(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    refreshed_transfers = wallet.refresh(online,None, [], False)
    return refreshed_transfers

@router.post("/wallet/backup")
def create_backup(req:Backup, wallet_dep: tuple[Wallet, object,str]=Depends(get_wallet)):
    wallet, online, xpub = wallet_dep
    remove_backup_if_exists(xpub)
    backup_path = get_backup_path(xpub)
    wallet.backup(backup_path, req.password)

    if not os.path.exists(backup_path):
        raise HTTPException(status_code=500, detail="Backup file was not created")

    return {
        "message": "Backup created successfully",
        "download_url": f"/wallet/backup/{xpub}"
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
    xpub: str = Form(...),
):
    remove_backup_if_exists(xpub)
    backup_path = get_backup_path(xpub)
    with open(backup_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        # Restore wallet from backup
        restore_wallet_instance(xpub, password, backup_path)
        return {"message": "Wallet restored successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to restore wallet: {str(e)}")