# Deposit & UTEXO API curl Examples

## Base URL
Assuming your FastAPI server is running on `http://localhost:8000`

---

## 1. Get Single-Use Deposit Address

```bash
curl -X GET "http://localhost:8000/wallet/single-use-address"
```

**Response:**
```json
{
  "address": "bc1q...",
  "expires_at": "2024-01-02T12:00:00Z"
}
```

**Notes:**
- Returns a single-use Bitcoin deposit address
- Funds sent to this address can be detected and credited to the wallet for:
  - Bitcoin L1 balance
  - UTEXO deposits
  - Asset-aware flows (RGB), depending on wallet configuration
- Each address is intended for one-time use only
- Once funds are detected, the address is considered used
- Reusing a single-use address is discouraged
- Address monitoring and crediting are handled automatically by the backend

---

## 2. Get Unused Deposit Addresses

```bash
curl -X GET "http://localhost:8000/wallet/unused-addresses"
```

**Response:**
```json
{
  "addresses": [
    {
      "address": "bc1q...",
      "created_at": "2024-01-01T12:00:00Z"
    },
    {
      "address": "bc1q...",
      "created_at": "2024-01-01T11:00:00Z"
    }
  ]
}
```

**Notes:**
- Returns a list of unused Bitcoin deposit addresses
- These addresses have been generated previously but have not yet received funds
- Only addresses with no detected deposits are returned
- Addresses may be automatically rotated or expired by the backend
- Recommended for wallets that pre-generate deposit addresses

---

## 3. Withdraw from UTEXO

```bash
curl -X POST "http://localhost:8000/wallet/withdraw-from-utexo" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "bc1q...",
    "amount_sats": 50000,
    "fee_rate": 1
  }'
```

**Response:**
```json
{
  "withdrawal_id": "uuid-here",
  "txid": null
}
```

**Notes:**
- Withdraws BTC from the UTEXO layer back to Bitcoin L1
- Creates a Bitcoin transaction that releases funds from UTEXO to a specified on-chain address
- `txid` will be `null` initially and set when the transaction is confirmed
- Use the `withdrawal_id` to track the withdrawal status

**Parameters:**
- `address` (string, required) - Bitcoin address to receive the withdrawal
- `amount_sats` (int, required) - Amount in satoshis to withdraw
- `fee_rate` (int, required) - Fee rate for the withdrawal transaction

---

## Quick Test Sequence

1. Get a single-use deposit address
2. List all unused deposit addresses
3. Withdraw from UTEXO using a Bitcoin address
4. Check withdrawal status using the withdrawal_id

