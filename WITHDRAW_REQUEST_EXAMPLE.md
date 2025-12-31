# Withdraw Request Examples

## POST /wallet/withdraw

### Minimal Request (withdraw max available)
```json
{
  "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfhrcndjf"
}
```

### With Specific Amount
```json
{
  "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfhrcndjf",
  "amount_sats": 100000
}
```

### With All Optional Parameters
```json
{
  "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfhrcndjf",
  "amount_sats": 100000,
  "source": "channels_only",
  "channel_ids": [
    "8129afe1b1d7cf60d5e1bf4c04b09bec925ed4df5417ceee0484e24f816a105a"
  ],
  "close_mode": "force",
  "fee_rate_sat_per_vb": 10,
  "deduct_fee_from_amount": true
}
```

### Auto Source (Default)
```json
{
  "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfhrcndjf",
  "amount_sats": 50000,
  "source": "auto"
}
```

### Cooperative Close (Default)
```json
{
  "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfhrcndjf",
  "amount_sats": 75000,
  "close_mode": "cooperative",
  "fee_rate_sat_per_vb": 5
}
```

## Response Example

```json
{
  "withdrawal_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "REQUESTED"
}
```

## Field Descriptions

- **address** (required): Bitcoin address to receive the withdrawal
- **amount_sats** (optional): Amount in satoshis to withdraw. If omitted, withdraws max available
- **source** (optional): Source of funds - `"onchain_only"`, `"channels_only"`, or `"auto"` (default: `"auto"`)
- **channel_ids** (optional): Specific channel IDs to close. If omitted, all eligible channels are closed
- **close_mode** (optional): Channel close mode - `"cooperative"` or `"force"` (default: `"cooperative"`)
- **fee_rate_sat_per_vb** (optional): Fee rate in satoshis per virtual byte. If omitted, uses default (5)
- **deduct_fee_from_amount** (optional): Whether to deduct fee from the withdrawal amount (default: `true`)

## cURL Example

```bash
curl -X POST "http://localhost:8000/wallet/withdraw" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfhrcndjf",
    "amount_sats": 100000,
    "source": "channels_only",
    "close_mode": "cooperative"
  }'
```

