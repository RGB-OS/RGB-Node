# RGB Node

🔐 Security & Trust Model (Important)
-------------------------------------

> **RGB Node is infrastructure software and is NOT intended to be used as a public shared service.**

Running RGB Node requires **explicit trust in the operator**, because the node:

-   Receives **wallet identifiers (xpubs, master fingerprint)**
-   Maintains **wallet state and UTXO sets**
-   Constructs **PSBTs for signing**
-   Observes **all wallet activity and transaction graph metadata**

While **private keys are never held by the RGB Node**, wallet privacy and transaction integrity **depend on the honesty and security of the server operator**.

### ⚠️ Threat model summary

If you use an RGB Node operated by a third party:

-   That operator can **observe all wallet activity**
-   Extended public keys **must be assumed disclosed**
-   A malicious or compromised server **could construct malicious PSBTs**
-   Privacy exposure is **permanent** for any xpub ever used

* * * * *

Deployment Recommendation (Strong)
----------------------------------

**RGB Node MUST be deployed inside infrastructure you control**, such as:

-   Exchange backend
-   Wallet backend
-   Internal settlement system
-   Enterprise custody environment

RGB Node is a drop‑in HTTP service for integrating RGB asset transfers on Bitcoin L1. It exposes a developer‑friendly REST API for wallets, exchanges, and apps to issue, receive, and transfer RGB assets without embedding the full RGB protocol logic in the client.

- Responsibilities: RGB state handling, invoice creation/decoding, PSBT building, UTXO maintenance, and transfer lifecycle management
- Non‑custodial: signing happens externally by a signer service or the client itself (via PSBT)
- Multi‑wallet: manage multiple RGB wallets concurrently via the API (separate xpubs/state)
- Built on `rgb-lib` maintained by [Bitfinex](https://github.com/RGB-Tools/rgb-lib)
- Full rgb-lib coverage: expose rgb-lib functionality through HTTP endpoints

## Client SDK

To simplify integration with the RGB Node from JavaScript/TypeScript backends, you can use the client SDK:

- `rgb-sdk`: a Node.js SDK that wraps the RGB Node API and common flows (invoice, UTXOs, PSBT build/sign/finalize, balances, transfers), making server integrations faster and more consistent. See the repository for usage examples and flow helpers: [`RGB-OS/rgb-sdk`](https://github.com/RGB-OS/rgb-sdk).

This SDK mirrors the API surface and patterns described here, and can be adapted to your signing setup (local mnemonic etc) and orchestration needs. It is well‑suited for building your own wallet backend or exchange integration. [Repository link](https://github.com/RGB-OS/rgb-sdk).

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

- Client wallets interact with the RGB Node over a simple REST API. This keeps wallet apps lightweight while enabling full RGB functionality.
- The node encapsulates RGB state and PSBT construction using `rgb-lib`. Private keys remain with the client or an external signer.
- Wallets can be “online” via the node: a wallet can be created/registered with the node and then use all RGB features (invoice creation, transfers, state refresh) through the API.
- Invoices embed transport endpoints (from `PROXY_ENDPOINT`) and can be paid by any RGB‑compatible wallet.

Typical flow for an online wallet:
- Create/register wallet on the node → node derives addresses/maintains UTXOs.
- Generate invoices (blinded or witness) and receive payments.
- Build PSBTs for outgoing transfers; sign client‑side or by a dedicated signer; submit to finalize.

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

Self‑host
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
- For production deployments, place the node behind your own API gateway and auth


## Configuration and operations

- `NETWORK` controls Bitcoin network selection for `rgb_lib`
- `PROXY_ENDPOINT` is propagated into transport endpoints for invoices and witness invoices


## Storage model

- **Wallet state**: Stored on the file system (`./data/`) due to current `rgb-lib` constraints
- **Refresh queue & watchers**: Stored in PostgreSQL for durability and recovery
- **Automatic recovery**: Active watchers are automatically recovered on startup

## External Signer

For production, pair the RGB Node with a dedicated signer service that holds keys in your environment and validates and signs PSBTs via secure messaging. See:

- Signer repository (TypeScript service): [`RGB-OS/thunderlink-signer`](https://github.com/RGB-OS/thunderlink-signer)

Typical use:
- RGB Node builds an unsigned PSBT via `/wallet/sendbegin`
- Signer receives a sign request over RabbitMQ, signs using your mnemonic, returns signed PSBT
- RGB Node finalizes via `/wallet/sendend`

This model keeps private keys off the RGB Node.

## Future roadmap

- Authentication/Authorization:
  - For self‑hosted deployments, customers should add their own JWT/auth middleware and gateway
- Pluggable storage for wallet state (PostgreSQL)
- Multi‑tenant admin endpoints and quota/rate‑limit hooks
- Observability: metrics endpoints and structured logs
- Extended rgb-lib surface area as new features land

## Refresh Worker

The RGB Node includes an automatic refresh worker that syncs wallet state when invoices are created or assets are sent. The worker runs as a separate service and automatically refreshes wallets until transfers are settled or failed.

### Running with Docker Compose

The refresh worker is included in `docker-compose.yml` and starts automatically:

```bash
docker compose up
```

This starts:
- `postgres` - PostgreSQL database (port 5432)
- `thunderlink-python` - FastAPI service (port 8000)
- `refresh-worker` - Background process (no port, connects to PostgreSQL and FastAPI)

Scale workers:
```bash
docker compose up --scale refresh-worker=3
```

### Running Manually

1. Start PostgreSQL:
```bash
# Using Docker
docker run -d --name postgres-rgb \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=rgb_node \
  -p 5432:5432 \
  postgres:15-alpine

# Or using local PostgreSQL
createdb rgb_node
psql rgb_node < migrations/001_initial_schema.sql
```

2. Start FastAPI:
```bash
uvicorn main:app --reload
```

3. Start Worker (in separate terminal):
```bash
python -m workers.refresh_worker
```

### Configuration

Add to your `.env` file:
```bash
POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/rgb_node
REFRESH_INTERVAL=100
MAX_REFRESH_RETRIES=10
ENABLE_RECOVERY=true
```

The worker automatically:
- Watches invoices until `SETTLED` or `FAILED`
- Refreshes wallet state after asset sends
- Retries with exponential backoff on failures
- Recovers active watchers on startup (if `ENABLE_RECOVERY=true`)


For more details, see [REFRESH_WORKER.md](./REFRESH_WORKER.md).
