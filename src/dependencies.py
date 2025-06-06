from fastapi import Header, HTTPException, Depends
from typing import Tuple
from rgb_lib import Wallet
from src.wallet_utils import load_wallet_instance,create_wallet_instance  # adjust your actual import

def get_wallet(xpub_van: str = Header(...),
    xpub_col: str = Header(...)) -> Tuple[Wallet, object, str, str]:
    wallet, online = load_wallet_instance(xpub_van, xpub_col)
    if not wallet or not online:
        raise HTTPException(status_code=400, detail="Wallet not initialized")
    return wallet, online, xpub_van, xpub_col

def create_wallet( xpub_van: str = Header(...),
    xpub_col: str = Header(...)) -> Tuple[Wallet, object, str,str]:
    wallet, online = create_wallet_instance(xpub_van, xpub_col)
    if not wallet or not online:
        raise HTTPException(status_code=400, detail="Wallet not initialized")
    return wallet, online, xpub_van, xpub_col
