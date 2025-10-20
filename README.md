# RGB Node (ThunderLink)

RGB Node is a drop‑in HTTP service for integrating RGB asset transfers on Bitcoin L1. It exposes a developer‑friendly REST API for wallets, exchanges, and apps to issue, receive, and transfer RGB assets without embedding the full RGB protocol logic in the client.

- Responsibilities: RGB state handling, invoice creation/decoding, PSBT building, UTXO maintenance, and transfer lifecycle management
- Non‑custodial: signing happens externally by a signer service or the client itself (via PSBT)
- Multi‑wallet: manage multiple RGB wallets concurrently via the API (separate xpubs/state)
- Full rgb-lib coverage: expose rgb-lib functionality through HTTP endpoints

References:
- Overview: [ThunderLink Overwiew](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/overwiew)
- Architecture, responsibilities, and API concepts: [ThunderLink RGB Node](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/rgb-manager)


## Client SDK

To simplify integration with the RGB Node from JavaScript/TypeScript backends, you can use the official client SDK:

- `rgb-connect-nodejs`: a Node.js SDK that wraps the RGB Node API and common flows (invoice, UTXOs, PSBT build/sign/finalize, balances, transfers), making server integrations faster and more consistent. See the repository for usage examples and flow helpers: [`RGB-OS/rgb-connect-nodejs`](https://github.com/RGB-OS/rgb-connect-nodejs).

This SDK mirrors the API surface and patterns described here, and can be adapted to your signing setup (local mnemonic etc) and orchestration needs. It is well‑suited for building your own wallet backend or exchange integration. [Repository link](https://github.com/RGB-OS/rgb-connect-nodejs).


## Features

- Issue RGB20 assets
- Create blinded and witness invoices
- Decode invoices
- Begin/send transfers (PSBT build), end transfers (broadcast + finalize)
- List assets, balances, UTXOs, transactions, and transfers
- Backup/restore wallet state
- Work with multiple wallets in parallel (e.g., per user/account/xpub)
- Provide a simple, intuitive interface for managing RGB assets and on‑chain transactions


## Architecture design

The RGB Node follows a clean separation of concerns inspired by the ThunderStack architecture:

- Client wallets interact with the RGB Node over a simple REST API. This keeps wallet apps lightweight while enabling full RGB functionality.
- The node encapsulates RGB state and PSBT construction using `rgb-lib`. Private keys remain with the client or an external signer.
- Wallets can be “online” via the node: a wallet can be created/registered with the node and then use all RGB features (invoice creation, transfers, state refresh) through the API.
- Invoices embed transport endpoints (from `PROXY_ENDPOINT`) and can be paid by any RGB‑compatible wallet.

Typical flow for an online wallet:
- Create/register wallet on the node → node derives addresses/maintains UTXOs.
- Generate invoices (blinded or witness) and receive payments.
- Build PSBTs for outgoing transfers; sign client‑side or by a dedicated signer; submit to finalize.

For more details see the ThunderStack docs: [Overwiew](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/overwiew), [RGB Node](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/rgb-manager).


## Wallet identification headers

Most wallet endpoints require headers to identify which wallet instance (state) to use. These headers are mandatory for endpoints that depend on a wallet (e.g., list assets, balances, create invoices, send, refresh):

- `xpub-van`: the vanilla (BTC) xpub for the wallet
- `xpub-col`: the colored (RGB) xpub for the wallet
- `master-fingerprint`: BIP32 master key fingerprint (hex)

Notes:
- Header names are case‑insensitive; dashes are required (`xpub-van`).
- Registration (`/wallet/register`) also uses these headers to initialize state for this wallet in the node.

Example:
```bash
curl -X POST :8000/wallet/listassets \
  -H 'xpub-van: xpub6...van' \
  -H 'xpub-col: xpub6...col' \
  -H 'master-fingerprint: ffffffff'
```


## Tech Stack

- Python 3.12
- FastAPI
- `rgb-lib` Python bindings (PSBT + RGB protocol integration)


## Quickstart

You have two options to run RGB Node:

1) [ThunderCloud](https://cloud.thunderstack.org/) managed deployment (recommended)
- Fully configurable and ready to use on ThunderCloud
- Launch, configure, and operate RGB Node with a few clicks
- 

2) Self‑host
- Use the Python or Docker instructions below
- Configure env vars like `NETWORK` and `PROXY_ENDPOINT`
- Pair with a signer if you want server‑side signing


### Prerequisites
- Python 3.12+
- Or Docker/Docker Compose

### Environment
Create an `.env` (or export env vars) if needed:

```bash
# Network: 0=Mainnet, 1=Testnet, 2=Signet, 3=Regtest (default)
export NETWORK=3

# Transport endpoint used in invoices (proxy or transport URL)
export PROXY_ENDPOINT=http://127.0.0.1:9090
```

The service reads:
- `NETWORK` → selects `rgb_lib.BitcoinNetwork`
- `PROXY_ENDPOINT` → used as transport endpoint for invoices

### Install and run (self‑host, local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Service will start on `http://127.0.0.1:8000` by default.

### Docker (self‑host)

```bash
docker build -t rgb-node .
docker run -p 8000:8000 \
  -e NETWORK=3 \
  -e PROXY_ENDPOINT=http://127.0.0.1:9090 \
  rgb-node
```

Or via Compose:

```bash
docker compose up --build
```


## API Overview

Below is a practical summary of key endpoints implemented in `src/routes.py`. Payload shapes are defined in `src/rgb_model.py`. All endpoints are `POST` unless specified.

Base URL examples:
- Local dev: `http://127.0.0.1:8000`

[API reference](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/rgb-manager/api-reference)

### Wallet bootstrap

- `POST /wallet/generate_keys` → generate network‑specific keys (xpubs/mnemonic material as applicable)
- `POST /wallet/register` → derive address and return on‑chain BTC balance snapshot
- `POST /wallet/address` → returns BTC address

Include headers for wallet selection:
```bash
curl -X POST :8000/wallet/register \
  -H 'xpub-van: xpub6...van' \
  -H 'xpub-col: xpub6...col' \
  -H 'master-fingerprint: ffffffff'
```


### UTXO management

- `POST /wallet/listunspents` → list UTXOs known to the node
- `POST /wallet/createutxosbegin` → build PSBT to create N UTXOs
- `POST /wallet/createutxosend` → finalize UTXO creation using a signed PSBT

Headers required (example):
```bash
curl -X POST :8000/wallet/listunspents \
  -H 'xpub-van: xpub6...van' \
  -H 'xpub-col: xpub6...col' \
  -H 'master-fingerprint: ffffffff'
```


### Assets and balances

- `POST /wallet/listassets` → list RGB assets 
- `POST /wallet/assetbalance` → get balance for `assetId`
- `POST /wallet/btcbalance` → get BTC balance (vanilla + colored)


### Invoice

- `POST /wallet/blindreceive` → create blinded invoice
- `POST /wallet/witnessreceive` → create witness invoice (wvout)
- `POST /wallet/decodergbinvoice` → decode invoice

Request model for receive:
```json
{
  "asset_id": "<rgb20 asset id>",
  "amount": 12345
}
```


### Send flow

1) Build PSBT → `POST /wallet/sendbegin`

Headers required:
```bash
-H 'xpub-van: xpub6...van' \
-H 'xpub-col: xpub6...col' \
-H 'master-fingerprint: ffffffff'
```

Request model:
```json
{
  "invoice": "<rgb invoice>",
  "asset_id": "<optional explicit asset id>",
  "amount": 12345,
  "witness_data": {
    "amount_sat": 1000,
    "blinding": null
  },
  "fee_rate": 5,
  "min_confirmations": 3
}
```
Rules:
- `recipient_id` is derived from the invoice; if it contains `wvout:` it’s a witness send
- For witness sends, `witness_data` is required and must include positive `amount_sat` (and optional `blinding`)
- For non‑witness sends, `witness_data` is ignored (treated as `null`)
- Optional `fee_rate` and `min_confirmations` default to 5 and 3 when not provided

Response:
```json
"<psbt base64>"
```

2) Sign PSBT on client 

3) Finalize → `POST /wallet/sendend`
```json
{
  "signed_psbt": "<base64>"
}
```
Response:
```json
{
  "txid": "<txid>",
  "batch_transfer_idx": 0
}
```


### History and maintenance

- `POST /wallet/listtransactions` → list on‑chain transactions
- `POST /wallet/listtransfers` → list RGB transfers for an asset
- `POST /wallet/refresh` → refresh wallet state
- `POST /wallet/sync` → sync wallet with network


### Backup and restore

- `POST /wallet/backup` → create encrypted backup
- `GET  /wallet/backup/{id}` → download backup
- `POST /wallet/restore` (multipart form) → restore from backup


## Security model

- The RGB Node never needs application private keys. It constructs PSBTs; signing is performed by a separate signer service or client app, then submitted back.
- For production deployments, place the node behind your own API gateway and auth. See the security guidance and architecture notes in the ThunderStack docs: [Overwiew](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/overwiew) and [RGB Node](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/rgb-manager).


## Configuration and operations

- `NETWORK` controls Bitcoin network selection for `rgb_lib`
- `PROXY_ENDPOINT` is propagated into transport endpoints for invoices and witness invoices


## Storage model

For now, wallet state is stored on the file system due to current `rgb-lib` constraints. In future versions, wallet state can be persisted in a relational database (e.g., PostgreSQL) to support HA, clustering, and backup/restore workflows beyond single-node storage.

## External Signer

For production, pair the RGB Node with a dedicated signer service that holds keys in your environment and signs PSBTs via secure messaging (RabbitMQ). See:

- RGB Signer docs (how it works, queues, security): [ThunderLink RGB Signer](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/rgb-signer)
- Signer repository (TypeScript service): [`RGB-OS/thunderlink-signer`](https://github.com/RGB-OS/thunderlink-signer)

Typical use:
- RGB Node builds an unsigned PSBT via `/wallet/sendbegin`
- Signer receives a sign request over RabbitMQ, signs using your mnemonic, returns signed PSBT
- RGB Node finalizes via `/wallet/sendend`

This model keeps private keys off the RGB Node and avoids any public-facing key material, matching the architecture outlined in the docs. [Signer docs](https://docs.thunderstack.org/bitcoin-native-infrastructure/readme/thunderlink/rgb-signer), [Repo](https://github.com/RGB-OS/thunderlink-signer).

## Future roadmap

- Authentication/Authorization:
  - When hosted in ThunderCloud, JWT authorization will be provided by ThunderStack (managed deployment)
  - For self‑hosted deployments, customers should add their own JWT/auth middleware and gateway
- Pluggable storage for wallet state (PostgreSQL)
- Multi‑tenant admin endpoints and quota/rate‑limit hooks
- Observability: metrics endpoints and structured logs
- Extended rgb-lib surface area as new features land





