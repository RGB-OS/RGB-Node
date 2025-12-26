# Lightning API curl Examples

## Base URL
Assuming your FastAPI server is running on `http://localhost:8000`

---

## 1. Create BTC Lightning Invoice

```bash
curl -X POST "http://localhost:8000/lightning/create-invoice" \
  -H "Content-Type: application/json" \
  -d '{
    "amount_sats": 1000,
    "description": "Test BTC invoice",
    "expiry_seconds": 3600
  }'
```

**Response:**
```json
{
  "id": "uuid-here",
  "invoice": "lnbc1000u1p3mock...",
  "status": "OPEN",
  "payment_type": "BTC",
  "amount_sats": 1000,
  "asset": null,
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

## 2. Create Asset Lightning Invoice

```bash
curl -X POST "http://localhost:8000/lightning/create-invoice" \
  -H "Content-Type: application/json" \
  -d '{
    "asset": {
      "asset_id": "rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw",
      "amount": 50
    },
    "description": "Test Asset invoice",
    "expiry_seconds": 3600
  }'
```

**Response:**
```json
{
  "id": "uuid-here",
  "invoice": "lnasset1p3mock...",
  "status": "OPEN",
  "payment_type": "ASSET",
  "amount_sats": null,
  "asset": {
    "asset_id": "rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw",
    "amount": 50
  },
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

## 3. Pay BTC Lightning Invoice

```bash
curl -X POST "http://localhost:8000/lightning/pay-invoice" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice": "lnbc1000u1p3mock...",
    "max_fee_sats": 10,
    "amount_sats_to_send": 1000
  }'
```

**Response:**
```json
{
  "id": "uuid-here",
  "status": "PENDING",
  "payment_type": "BTC",
  "amount_sats": 1000,
  "asset": null,
  "fee_sats": null,
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

## 4. Pay Asset Lightning Invoice

```bash
curl -X POST "http://localhost:8000/lightning/pay-invoice" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice": "lnasset1p3mock...",
    "max_fee_sats": 10,
    "asset": {
      "asset_id": "rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw",
      "amount": 50
    }
  }'
```

**Response:**
```json
{
  "id": "uuid-here",
  "status": "PENDING",
  "payment_type": "ASSET",
  "amount_sats": null,
  "asset": {
    "asset_id": "rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw",
    "amount": 50
  },
  "fee_sats": null,
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

## 5. Get Lightning Send Request Status

```bash
curl -X GET "http://localhost:8000/lightning/send-request/{request_id}"
```

Replace `{request_id}` with the ID returned from the pay-invoice endpoint.

---

## 6. Get Lightning Receive Request Status

```bash
curl -X GET "http://localhost:8000/lightning/receive-request/{request_id}"
```

Replace `{request_id}` with the ID returned from the create-invoice endpoint.

---

## 7. Get Lightning Fee Estimate

### For BTC Invoice:
```bash
curl -X POST "http://localhost:8000/lightning/fee-estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice": "lnbc1000u1p3mock..."
  }'
```

### For Asset Invoice:
```bash
curl -X POST "http://localhost:8000/lightning/fee-estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice": "lnasset1p3mock...",
    "asset": {
      "asset_id": "rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw",
      "amount": 50
    }
  }'
```

**Response:**
```json
10
```

---

## Quick Test Sequence

1. Create a BTC invoice and save the invoice string
2. Pay that invoice using the invoice string
3. Check the payment status using the request ID from step 2
4. Check the invoice status using the request ID from step 1


