import os
import json
from rgb_lib import Wallet, WalletData, BitcoinNetwork, DatabaseType

NETWORK = BitcoinNetwork.REGTEST
BASE_PATH = "./data"
vanilla_keychain = 1

class WalletNotFoundError(Exception):
    pass

def get_wallet_path(client_id: str):
    return os.path.join(BASE_PATH, client_id)

def get_wallet_config_path(client_id: str):
    return os.path.join(get_wallet_path(client_id), "wallet.json")

def save_wallet_config(client_id: str, config: dict):
    os.makedirs(get_wallet_path(client_id), exist_ok=True)
    with open(get_wallet_config_path(client_id), "w") as f:
        json.dump(config, f, indent=2)

def load_wallet_config(client_id: str):
    path = get_wallet_config_path(client_id)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

def create_wallet_instance(client_id: str):
    config_path = get_wallet_path(client_id)

    if not os.path.exists(config_path):
        os.makedirs(get_wallet_path(client_id), exist_ok=True)
        # raise WalletNotFoundError(f"Wallet for client '{client_id}' does not exist.")
    wallet_data = WalletData(
        data_dir=get_wallet_path(client_id),
         bitcoin_network=NETWORK,
        database_type=DatabaseType.SQLITE,
        pubkey=client_id,
        mnemonic=None,
        max_allocations_per_utxo=1,
        vanilla_keychain=vanilla_keychain,
    )
    wallet = Wallet(wallet_data)
    online = wallet.go_online(False, "regtest.thunderstack.org:50001")
    return wallet, online

def load_wallet_instance(client_id: str):
    config_path = get_wallet_path(client_id)
    print("load_wallet_instance",config_path)
    if not os.path.exists(config_path):
        raise WalletNotFoundError(f"Wallet for client '{client_id}' does not exist.")

    wallet_data = WalletData(
        data_dir=get_wallet_path(client_id),
        bitcoin_network=NETWORK,
        database_type=DatabaseType.SQLITE,
        pubkey=client_id,
        mnemonic=None,
        max_allocations_per_utxo=1,
        vanilla_keychain=vanilla_keychain,
    )
    wallet = Wallet(wallet_data)
    online = wallet.go_online(False, "regtest.thunderstack.org:50001")
    return wallet, online
