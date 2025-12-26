#!/bin/bash

# Lightning API curl examples
# Make sure your FastAPI server is running (default: http://localhost:8000)

BASE_URL="http://localhost:8000"

echo "=== Lightning API Examples ==="
echo ""

# 1. Create BTC Lightning Invoice
echo "1. Creating BTC Lightning Invoice..."
echo "curl -X POST \"${BASE_URL}/lightning/create-invoice\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"amount_sats\": 1000, \"description\": \"Test BTC invoice\", \"expiry_seconds\": 3600}'"
echo ""

BTC_INVOICE_RESPONSE=$(curl -s -X POST "${BASE_URL}/lightning/create-invoice" \
  -H "Content-Type: application/json" \
  -d '{"amount_sats": 1000, "description": "Test BTC invoice", "expiry_seconds": 3600}')

echo "Response: $BTC_INVOICE_RESPONSE"
echo ""

# Extract invoice from response (using jq if available, otherwise manual parsing)
BTC_INVOICE=$(echo $BTC_INVOICE_RESPONSE | grep -o '"invoice":"[^"]*' | cut -d'"' -f4)
echo "Extracted Invoice: $BTC_INVOICE"
echo ""

# 2. Create Asset Lightning Invoice
echo "2. Creating Asset Lightning Invoice..."
echo "curl -X POST \"${BASE_URL}/lightning/create-invoice\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"asset\": {\"asset_id\": \"rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw\", \"amount\": 50}, \"description\": \"Test Asset invoice\"}'"
echo ""

ASSET_INVOICE_RESPONSE=$(curl -s -X POST "${BASE_URL}/lightning/create-invoice" \
  -H "Content-Type: application/json" \
  -d '{"asset": {"asset_id": "rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw", "amount": 50}, "description": "Test Asset invoice"}')

echo "Response: $ASSET_INVOICE_RESPONSE"
echo ""

# Extract invoice from response
ASSET_INVOICE=$(echo $ASSET_INVOICE_RESPONSE | grep -o '"invoice":"[^"]*' | cut -d'"' -f4)
echo "Extracted Invoice: $ASSET_INVOICE"
echo ""

# 3. Pay BTC Lightning Invoice
echo "3. Paying BTC Lightning Invoice..."
echo "curl -X POST \"${BASE_URL}/lightning/pay-invoice\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"invoice\": \"$BTC_INVOICE\", \"max_fee_sats\": 10, \"amount_sats_to_send\": 1000}'"
echo ""

PAY_BTC_RESPONSE=$(curl -s -X POST "${BASE_URL}/lightning/pay-invoice" \
  -H "Content-Type: application/json" \
  -d "{\"invoice\": \"$BTC_INVOICE\", \"max_fee_sats\": 10, \"amount_sats_to_send\": 1000}")

echo "Response: $PAY_BTC_RESPONSE"
echo ""

# Extract request ID from response
PAY_REQUEST_ID=$(echo $PAY_BTC_RESPONSE | grep -o '"id":"[^"]*' | cut -d'"' -f4)
echo "Payment Request ID: $PAY_REQUEST_ID"
echo ""

# 4. Pay Asset Lightning Invoice
echo "4. Paying Asset Lightning Invoice..."
echo "curl -X POST \"${BASE_URL}/lightning/pay-invoice\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"invoice\": \"$ASSET_INVOICE\", \"max_fee_sats\": 10, \"asset\": {\"asset_id\": \"rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw\", \"amount\": 50}}'"
echo ""

PAY_ASSET_RESPONSE=$(curl -s -X POST "${BASE_URL}/lightning/pay-invoice" \
  -H "Content-Type: application/json" \
  -d "{\"invoice\": \"$ASSET_INVOICE\", \"max_fee_sats\": 10, \"asset\": {\"asset_id\": \"rgb:Um_oNgUu-VVd9iE3-WWkKuNW-14eQ~KB-YTtxRUu-pF~TiPw\", \"amount\": 50}}")

echo "Response: $PAY_ASSET_RESPONSE"
echo ""

echo "=== Done ==="


