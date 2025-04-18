from fastapi import Header, HTTPException, Depends
from typing import Tuple
from rgb_lib import Wallet
from src.wallet_utils import load_wallet_instance,create_wallet_instance  # adjust your actual import

def get_wallet(xpub: str = Header(...)) -> Tuple[Wallet, object]:
    wallet, online = load_wallet_instance(xpub)
    if not wallet or not online:
        raise HTTPException(status_code=400, detail="Wallet not initialized")
    return wallet, online

def create_wallet(xpub: str = Header(...)) -> Tuple[Wallet, object]:
    wallet, online = create_wallet_instance(xpub)
    if not wallet or not online:
        raise HTTPException(status_code=400, detail="Wallet not initialized")
    return wallet, online
