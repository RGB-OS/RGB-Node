import os
import json
from rgb_lib import Wallet,restore_backup, WalletData, BitcoinNetwork, DatabaseType
print("NETWORK raw =", os.getenv("NETWORK"))
print("INDEXER_URL raw =", os.getenv("INDEXER_URL"))
print("PROXY_ENDPOINT raw =", os.getenv("PROXY_ENDPOINT"))
env_network = int(os.getenv("NETWORK", "3"))
NETWORK = BitcoinNetwork(env_network)
BASE_PATH = "./data"
RESTORED_PATH = './data'
BACKUP_PATH = './backup'
vanilla_keychain = 1
wallet_instances: dict[str, dict[str, object]] = {}
INDEXER_URL = os.getenv('INDEXER_URL')

if INDEXER_URL is None:
    raise EnvironmentError("Missing required env var: INDEXER_URL")

class WalletNotFoundError(Exception):
    pass

def get_wallet_path(client_id: str):
    return os.path.join(BASE_PATH, client_id)
def get_restored_wallet_path(client_id: str):
    return os.path.join(RESTORED_PATH, client_id)

def remove_backup_if_exists(client_id: str):
    backup = os.path.join(BACKUP_PATH, f"{client_id}.backup")
    if os.path.exists(backup):
        os.remove(backup)

def get_backup_path(client_id: str): 
    os.makedirs(BACKUP_PATH, exist_ok=True)
    return os.path.join(BACKUP_PATH, f"{client_id}.backup")

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
    print("init wallet network:",NETWORK)
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
    print("prepere online",INDEXER_URL)
    online = wallet.go_online(False,INDEXER_URL)
    print("wallet online")
    wallet_instances[client_id] = {
        "wallet": wallet,
        "online": online
    }
    return wallet, online

def upload_backup(client_id: str):
    remove_backup_if_exists(client_id)
    backup_path = get_backup_path(client_id)
  
def restore_wallet_instance(client_id: str, password: str,backup_path: str):
    restore_path = get_restored_wallet_path(client_id)
    if not os.path.exists(restore_path):
        os.makedirs(get_restored_wallet_path(client_id), exist_ok=True)
        # raise WalletNotFoundError(f"Wallet for client '{client_id}' does not exist.")
    restore_backup(backup_path, password, restore_path)
    wallet_data = WalletData(
        data_dir=restore_path,
         bitcoin_network=NETWORK,
        database_type=DatabaseType.SQLITE,
        pubkey=client_id,
        mnemonic=None,
        max_allocations_per_utxo=1,
        vanilla_keychain=vanilla_keychain,
    )
    wallet = Wallet(wallet_data)
    online = wallet.go_online(False,INDEXER_URL)
    return wallet, online

def load_wallet_instance(client_id: str):
    if client_id in wallet_instances:
        instance = wallet_instances[client_id]
        if instance.get("wallet") and instance.get("online"):
            return instance["wallet"], instance["online"]
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
    online = wallet.go_online(False, INDEXER_URL)
    wallet_instances[client_id] = {
        "wallet": wallet,
        "online": online
    }
    return wallet, online

def refresh_wallet_instance(client_id: str):
    if client_id in wallet_instances:
        del wallet_instances[client_id]
    return load_wallet_instance(client_id)