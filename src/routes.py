from fastapi import HTTPException
from pydantic import BaseModel
from src.dependencies import get_wallet,create_wallet
from rgb_lib import BitcoinNetwork, Wallet,AssetSchema
from src.rgb_model import IssueAssetNiaRequestModel
from fastapi import APIRouter, Depends

NETWORK = BitcoinNetwork.REGTEST
router = APIRouter()
invoices = {}
PROXY_URL = "rpc://regtest.thunderstack.org:3000/json-rpc"
vanilla_keychain = 1

class WatchOnly(BaseModel):
    xpub: str

class CreateUtxosBegin(BaseModel):
    xpub: str
    mnemonic: str = None
    upTo: bool = False
    num: int = 5
    size: int = 1000
    feeRate: float = 1.0

class CreateUtxosEnd(BaseModel):
    xpub: str
    signedPsbt: str
class AssetBalanceRequest(BaseModel):
    xpub: str
    assetId: str
class InvoiceRequest(BaseModel):
    xpub: str
    assetId: str
    amount: int

@router.post("/wallet/create")
def create_wallet(wallet_dep: tuple[Wallet, object]=Depends(create_wallet)):
    wallet, online = wallet_dep
    btc_balance = wallet.get_btc_balance(online, False)
    address = wallet.get_address()
    return { "address": address, "btc_balance": btc_balance }

@router.post("/wallet/list-unspents")
def list_unspents(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    unspents = wallet.list_unspents(online, False, False)
    address = wallet.get_address()
    return { "unspents": unspents, "address": address }

@router.post("/wallet/create-utxos-begin")
def create_utxos_begin(req: CreateUtxosBegin, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    psbt = wallet.create_utxos_begin(online, req.upTo, req.num, req.size, req.feeRate, False)
    address = wallet.get_address()
    return { "psbt": psbt, "address": address }

@router.post("/wallet/create-utxos-end")
def create_utxos_end(req: CreateUtxosEnd, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    result = wallet.create_utxos_end(online, req.signedPsbt, False)
    return { "utxosCreated": result }

@router.post("/wallet/list-assets")
def list_assets(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    wallet.sync(online)
    assets = wallet.list_assets([AssetSchema.NIA])
    return { "assets": assets }

@router.post("/wallet/btc-balance")
def get_btc_balance(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    btc_balance = wallet.get_btc_balance(online, False)
    return { "btc_balance": btc_balance }

@router.post("/wallet/issue-asset-nia")
def issue_asset_nia(req: IssueAssetNiaRequestModel, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    asset = wallet.issue_asset_nia(online, req.amounts, req.ticker, req.name, req.precision, False)
    return { "issue_asset_nia": asset }

@router.post("/wallet/get-asset-balance")
def get_asset_balance(req: AssetBalanceRequest, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, _ = wallet_dep
    balance = wallet.get_asset_balance(req.assetId)
    return { "asset_balance": balance }

@router.post("/blind-receive")
def generate_invoice(req: InvoiceRequest, wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    receive = wallet.blind_receive(None, req.amount, None, ["regtest.thunderstack.org:3000/json-rpc"], 1)
    return { "blind_receive": receive }

@router.get("/invoice/{invoice_id}/status")
def invoice_status(invoice_id: str):
    invoice = invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return { "status": invoice["status"] }

@router.post("/wallet/refresh")
def refresh_wallet(wallet_dep: tuple[Wallet, object]=Depends(get_wallet)):
    wallet, online = wallet_dep
    wallet.refresh(online, None, [], False)
    return { "message": "Wallet refreshed" }

@router.post("/wallet/drop")
def drop_wallet():
    path = "./data/wallet.json"
    if os.path.exists(path):
        os.remove(path)
    return { "message": "Wallet config deleted" }

# @app.post("/wallet/create")
# def create_wallet(req: WatchOnly):
#     print("Creating wallet...")
#     wallet, online = create_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     btc_balance = wallet.get_btc_balance(online, False)
#     address = wallet.get_address()
#     return { "data":"","address":address,"btc_balance":btc_balance }

# @app.post("/wallet/list-unspents")
# def list_unspents(req: WatchOnly):
#     print("list-unspents",req.xpub)
#     wallet, online = load_wallet_instance(req.xpub)
#     print("list-load_wallet_instance")
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     unspents = wallet.list_unspents(online, False, False)
#     address = wallet.get_address()
#     return { "unspents": unspents, "address": address }

# @app.post("/wallet/create-utxos-begin")
# def create_utxos_begin(req: CreateUtxosBegin):
#     print(req)
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     psbt = wallet.create_utxos_begin(online, req.upTo, req.num, req.size,1,False)
#     address = wallet.get_address()
#     return { "psbt": psbt, address: address }

# @app.post("/wallet/create-utxos-end")
# def create_utxos_end(req: CreateUtxosEnd):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")

#     result = wallet.create_utxos_end(online, req.signedPsbt, False)
#     return { "utxosCreated": result }


# @app.post("/wallet/list-assets")
# def list_assets(req: WatchOnly):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     wallet.sync(online)
#     assets = wallet.list_assets([AssetSchema.NIA])
#     return { "assets": assets }

# @app.post("/wallet/btc-balance")
# def get_balance(req: WatchOnly):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     btc_balance = wallet.get_btc_balance(online, False)
#     return { "btc_balance": btc_balance }

# @app.post("/wallet/issue_asset_nia")
# def issue_asset_nia(req: IssueAssetNiaRequestModel,xpub: str = Header(...)):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     issue_asset_nia = wallet.issue_asset_nia(online, req.amounts, req.ticker, req.name, req.precision, False)
#     return { "issue_asset_nia": issue_asset_nia }

# @app.post("/wallet/get-asset-balance")
# def get_asset_balance(req: AssetBalanceRequest):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     asset_balance = wallet.get_asset_balance(req.assetId)
#     return { "asset_balance": asset_balance }

# @app.post("/blind-receive")
# def generate_invoice(req: InvoiceRequest):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     receive = wallet.blind_receive(None, req.amount, None, [PROXY_URL], 1)
#     return { "blind-receive": receive }


# @app.get("/invoice/{invoice_id}/status")
# def invoice_status(invoice_id: str):
#     invoice = invoices.get(invoice_id)
#     if not invoice:
#         raise HTTPException(status_code=404, detail="Invoice not found")
#     return { "status": invoice["status"] }


# @app.post("/wallet/refresh")
# def refresh_wallet(req: WatchOnly):
#     wallet, online = load_wallet_instance(req.xpub)
#     if not wallet or not online:
#         raise HTTPException(status_code=400, detail="Wallet not initialized")
#     wallet.refresh(online, None, [], False)
#     return { "message": "Wallet refreshed" }


# @app.post("/wallet/drop")
# def drop_wallet():
#     if os.path.exists("./data/wallet.json"):
#         os.remove("./data/wallet.json")
#     return { "message": "Wallet config deleted" }
