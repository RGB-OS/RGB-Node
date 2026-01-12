"""RLN (RGB Lightning Node) client for interacting with RLN node API."""
import os
import httpx
import logging
from typing import Optional, List, Dict, Any, Literal
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class RLNClient:
    """Client for interacting with RLN node API."""
    
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        """
        Initialize RLN client.
        
        Args:
            base_url: Base URL of the RLN node. If not provided, reads from RLN_NODE_URL env var.
            token: Authentication token. If not provided, reads from RLN_NODE_TOKEN env var.
        """
        self.base_url = base_url or os.getenv("RLN_NODE_URL", "http://localhost:3000")
        if not self.base_url:
            raise ValueError("RLN_NODE_URL environment variable must be set or base_url must be provided")
        
        # Remove trailing slash if present
        self.base_url = self.base_url.rstrip("/")
        
        # Get token from parameter or environment variable
        self.token = token or os.getenv("RLN_NODE_TOKEN")
        
        # Prepare headers
        self.headers = {}
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        
        # Reusable HTTP client instance (timeout can be overridden per request)
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """
        Get or create the HTTP client instance.
        
        Returns:
            httpx.AsyncClient: HTTP client instance
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),  # Default timeout, can be overridden per request
                headers=self.headers
            )
        return self._client
    
    async def _make_request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        timeout: float = 30.0,
        json: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make a request to the RLN node and handle all errors.
        
        Args:
            method: HTTP method (e.g., "POST", "GET")
            endpoint: API endpoint (e.g., "/address")
            timeout: Request timeout in seconds
            json: Optional JSON payload
            
        Returns:
            Dict[str, Any]: Parsed JSON response
            
        Raises:
            HTTPException: If the request fails or returns an error
        """
        url = f"{self.base_url}{endpoint}"
        client = await self._get_client()
        
        logger.debug(f"Making {method} request to {url}")
        logger.debug(f"Headers: {self.headers}")
        logger.debug(f"JSON payload: {json}")
        
        try:
            # Make request using httpx's method attribute with per-request timeout
            request_method = getattr(client, method.lower())
            
            # For POST requests, always include Content-Type header
            request_headers = {**self.headers}
            if method.upper() == "POST":
                request_headers["Content-Type"] = "application/json"
            
            request_kwargs = {
                "timeout": httpx.Timeout(timeout),
                "headers": request_headers
            }
            
            if json is not None:
                request_kwargs["json"] = json
            
            logger.debug(f"Request kwargs: {request_kwargs}")
            
            response = await request_method(url, **request_kwargs)
            
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            if response.status_code >= 400:
                logger.error(f"Error response body: {response.text}")
            
            # Parse response once
            try:
                response_data = response.json()
            except ValueError:
                response_data = None
            
            # Check for error responses
            if not response.is_success:
                if response_data:
                    # Use the error code from response, or fall back to HTTP status code
                    error_code = response_data.get("code", response.status_code)
                    status_code = error_code if isinstance(error_code, int) else response.status_code
                    
                    # Return the same error response structure from RLN node
                    raise HTTPException(
                        status_code=status_code,
                        detail=response_data
                    )
                else:
                    # If response is not valid JSON, use the response text or status
                    raise HTTPException(
                        status_code=response.status_code,
                        detail={"error": response.text or response.reason_phrase, "code": response.status_code}
                    )
            
            if response_data is None:
                raise HTTPException(
                    status_code=500,
                    detail="Invalid response from RLN node: response is not valid JSON"
                )
            
            return response_data
            
        except HTTPException:
            raise
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to communicate with RLN node: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error communicating with RLN node: {str(e)}"
            )
    
    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
    
    async def get_address(self) -> str:
        """
        Get a new Bitcoin address from the internal BDK wallet.
        
        Returns:
            str: Bitcoin address
            
        Raises:
            HTTPException: If the request fails
        """
        data = await self._make_request("POST", "/address")
        address = data.get("address")
        if not address:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: missing or empty 'address' field"
            )
        return address
    
    async def get_unused_addresses(self) -> List[Dict[str, str]]:
        """
        Get a list of unused Bitcoin addresses from the internal BDK wallet.
        
        Returns:
            List[Dict[str, str]]: List of unused addresses with 'address' and 'created_at' fields
            
        Raises:
            HTTPException: If the request fails
        """
        data = await self._make_request("POST", "/addresses")
        
        # Handle different response formats
        if isinstance(data, list):
            # If response is a list directly
            addresses = data
        elif isinstance(data, dict) and "addresses" in data:
            # If response has an "addresses" key
            addresses = data["addresses"]
        else:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: unexpected format"
            )
        
        # Validate and return addresses
        if not isinstance(addresses, list):
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: addresses is not a list"
            )
        
        return addresses
    
    async def send_btc(self, address: str, amount: int, fee_rate: int, skip_sync: bool = False) -> str:
        """
        Send BTC from UTEXO to a Bitcoin address.
        
        Args:
            address: Bitcoin address to send to
            amount: Amount in satoshis
            fee_rate: Fee rate for the transaction
            skip_sync: Whether to skip wallet sync
            
        Returns:
            str: Transaction ID (txid)
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "amount": amount,
            "address": address,
            "fee_rate": fee_rate,
            "skip_sync": skip_sync
        }
        
        data = await self._make_request("POST", "/sendbtc", timeout=60.0, json=payload)
        txid = data.get("txid")
        if not txid:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: missing or empty 'txid' field"
            )
        return txid
    
    async def create_lightning_invoice(
        self,
        amt_msat: int,
        expiry_sec: int,
        asset_id: Optional[str] = None,
        asset_amount: Optional[int] = None
    ) -> str:
        """
        Create a Lightning invoice (BTC or asset).
        
        Args:
            amt_msat: Amount in millisatoshis
            expiry_sec: Invoice expiration time in seconds
            asset_id: Optional asset ID for asset invoices
            asset_amount: Optional asset amount for asset invoices
            
        Returns:
            str: Lightning invoice string
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "amt_msat": amt_msat,
            "expiry_sec": expiry_sec
        }
        
        # Add asset fields if provided
        if asset_id is not None and asset_amount is not None:
            payload["asset_id"] = asset_id
            payload["asset_amount"] = asset_amount
        
        data = await self._make_request("POST", "/lninvoice", timeout=30.0, json=payload)
        invoice = data.get("invoice")
        if not invoice:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: missing or empty 'invoice' field"
            )
        return invoice
    
    async def get_invoice_status(self, invoice: str) -> str:
        """
        Get the status of a Lightning invoice.
        
        Args:
            invoice: Lightning invoice string
            
        Returns:
            str: Invoice status (Pending, Succeeded, Failed, Expired)
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "invoice": invoice
        }
        
        data = await self._make_request("POST", "/invoicestatus", timeout=30.0, json=payload)
        status = data.get("status")
        if not status:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: missing or empty 'status' field"
            )
        return status
    
    async def send_payment(self, invoice: str) -> Dict[str, Any]:
        """
        Send a Lightning payment.
        
        Args:
            invoice: Lightning invoice string
            
        Returns:
            Dict[str, Any]: Payment response with payment_hash, payment_secret, and status
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "invoice": invoice
        }
        
        data = await self._make_request("POST", "/sendpayment", timeout=60.0, json=payload)
        
        payment_hash = data.get("payment_hash")
        payment_secret = data.get("payment_secret")
        status = data.get("status")
        
        if not payment_hash or not status:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: missing required fields"
            )
        
        return {
            "payment_hash": payment_hash,
            "payment_secret": payment_secret,
            "status": status
        }
    
    async def decode_lightning_invoice(self, invoice: str) -> Dict[str, Any]:
        """
        Decode a Lightning invoice to get its details.
        
        Args:
            invoice: Lightning invoice string
            
        Returns:
            Dict[str, Any]: Decoded invoice data with amt_msat, expiry_sec, asset_id, etc.
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "invoice": invoice
        }
        
        data = await self._make_request("POST", "/decodelninvoice", timeout=30.0, json=payload)
        return data

    async def decode_rgb_invoice(self, invoice: str) -> Dict[str, Any]:
        """
        Decode an RGB invoice to get its details.
        
        Args:
            invoice: RGB invoice string (starts with "rgb:")
            
        Returns:
            Dict[str, Any]: Decoded invoice data with recipient_id, recipient_type, asset_schema,
            asset_id, assignment, network, expiration_timestamp, transport_endpoints
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "invoice": invoice
        }
        
        logger.debug("Decoding RGB invoice on RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/decodergbinvoice", timeout=30.0, json=payload)
        logger.debug(f"Decode RGB invoice response: {data}")
        return data
    
    async def get_btc_balance(self, skip_sync: bool = False) -> Dict[str, Any]:
        """
        Get BTC balance from the RLN node.
        
        Args:
            skip_sync: Whether to skip wallet sync
            
        Returns:
            Dict[str, Any]: BTC balance with vanilla and colored balances
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "skip_sync": skip_sync
        }
        logger.debug("Getting BTC balance from RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/btcbalance", timeout=30.0, json=payload)
        logger.debug(f"BTC balance response: {data}")
        return data
    
    async def list_assets(self, filter_asset_schemas: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        List assets from the RLN node.
        
        Args:
            filter_asset_schemas: Optional list of asset schemas to filter (e.g., ["Nia"])
            
        Returns:
            Dict[str, Any]: Assets data with nia, cfa, uda arrays
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {}
        if filter_asset_schemas:
            payload["filter_asset_schemas"] = filter_asset_schemas
        
        logger.debug(f"Listing assets with filter: {filter_asset_schemas}")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/listassets", timeout=30.0, json=payload)
        logger.debug(f"Assets response: {data}")
        return data
    
    async def create_rgb_invoice(
        self,
        min_confirmations: int = 1,
        duration_seconds: int = 86400,
        witness: bool = False
    ) -> Dict[str, Any]:
        """
        Create an RGB invoice for receiving assets.
        
        Args:
            min_confirmations: Minimum confirmations required
            duration_seconds: Invoice expiration duration in seconds
            witness: Whether to create a witness invoice
            
        Returns:
            Dict[str, Any]: Invoice data with recipient_id, invoice, expiration_timestamp, batch_transfer_idx
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "min_confirmations": min_confirmations,
            "duration_seconds": duration_seconds,
            "witness": witness
        }
        
        logger.debug("Creating RGB invoice")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/rgbinvoice", timeout=30.0, json=payload)
        logger.debug(f"RGB invoice response: {data}")
        return data
    
    async def list_channels(self) -> Dict[str, Any]:
        """
        List Lightning channels from the RLN node.
        
        Returns:
            Dict[str, Any]: Channels data with channels array
            
        Raises:
            HTTPException: If the request fails
        """
        logger.debug("Listing channels from RLN node")
        data = await self._make_request("GET", "/listchannels", timeout=30.0)
        logger.debug(f"Channels response: {data}")
        return data
    
    async def list_transfers(self, asset_id: str) -> Dict[str, Any]:
        """
        List transfers for a specific asset from the RLN node.
        
        Args:
            asset_id: Asset ID to list transfers for
            
        Returns:
            Dict[str, Any]: Transfers data with transfers array
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "asset_id": asset_id
        }
        
        logger.debug("Listing transfers from RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/listtransfers", timeout=30.0, json=payload)
        logger.debug(f"Transfers response: {data}")
        return data
    
    async def refresh_transfers(self, skip_sync: bool = False) -> Dict[str, Any]:
        """
        Refresh transfers on the RLN node.
        
        Args:
            skip_sync: Whether to skip wallet sync
            
        Returns:
            Dict[str, Any]: Response from refresh operation
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "skip_sync": skip_sync
        }
        
        logger.debug("Refreshing transfers on RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/refreshtransfers", timeout=30.0, json=payload)
        logger.debug(f"Refresh transfers response: {data}")
        return data
    
    async def open_channel(self, channel_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Open a Lightning channel on the RLN node.
        
        Args:
            channel_config: Channel configuration dictionary with fields like:
                - peer_pubkey_and_opt_addr
                - capacity_sat
                - push_msat
                - public
                - with_anchors
                - fee_base_msat
                - fee_proportional_millionths
                - temporary_channel_id
                - asset_id (optional, for asset channels)
                - asset_amount (optional, for asset channels)
                
        Returns:
            Dict[str, Any]: Response from open channel operation
            
        Raises:
            HTTPException: If the request fails
        """
        logger.debug("Opening channel on RLN node")
        logger.debug(f"Channel config: {channel_config}")
        data = await self._make_request("POST", "/openchannel", timeout=60.0, json=channel_config)
        logger.debug(f"Open channel response: {data}")
        return data
    
    async def get_payment(self, payment_hash: str) -> Dict[str, Any]:
        """
        Get payment status from the RLN node.
        
        Args:
            payment_hash: Payment hash to query
            
        Returns:
            Dict[str, Any]: Payment data with payment object containing:
                - amt_msat
                - asset_amount
                - asset_id
                - payment_hash
                - inbound
                - status
                - created_at
                - updated_at
                - payee_pubkey
                
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "payment_hash": payment_hash
        }
        
        logger.debug("Getting payment status from RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/getpayment", timeout=30.0, json=payload)
        logger.debug(f"Payment response: {data}")
        return data
    
    async def list_payments(self) -> Dict[str, Any]:
        """
        List all payments from the RLN node.
        
        Returns:
            Dict[str, Any]: Payments data with payments array containing payment objects
            
        Raises:
            HTTPException: If the request fails
        """
        logger.debug("Listing payments from RLN node")
        data = await self._make_request("POST", "/listpayments", timeout=30.0, json={})
        logger.debug(f"Payments response: {data}")
        return data
        
    
    async def list_transactions(self, skip_sync: bool = False) -> Dict[str, Any]:
        """
        List transactions from the RLN node.
        
        Args:
            skip_sync: Whether to skip wallet sync
            
        Returns:
            Dict[str, Any]: Transactions data with transactions array
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "skip_sync": skip_sync
        }
        
        logger.debug("Listing transactions from RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/listtransactions", timeout=30.0, json=payload)
        logger.debug(f"Transactions response: {data}")
        return data

    async def fail_transfers(
        self,
        batch_transfer_idx: int,
        no_asset_only: bool = False,
        skip_sync: bool = False
    ) -> Dict[str, Any]:
        """
        Fail transfers for a given batch transfer index.
        
        Args:
            batch_transfer_idx: Batch transfer index
            no_asset_only: Whether to fail only non-asset transfers
            skip_sync: Whether to skip sync
            
        Returns:
            Response with transfers_changed status
        """
        payload = {
            "batch_transfer_idx": batch_transfer_idx,
            "no_asset_only": no_asset_only,
            "skip_sync": skip_sync
        }
        
        logger.debug("Failing transfers on RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/failtransfers", timeout=30.0, json=payload)
        logger.debug(f"Fail transfers response: {data}")
        return data

    async def send_asset(
        self,
        asset_id: str,
        assignment: Dict[str, Any],
        recipient_id: str,
        witness_data: Optional[Dict[str, Any]] = None,
        donation: bool = False,
        fee_rate: int = 5,
        min_confirmations: int = 1,
        transport_endpoints: Optional[List[str]] = None,
        skip_sync: bool = False
    ) -> str:
        """
        Send an asset using RGB invoice or recipient ID.
        
        Args:
            asset_id: Asset ID to send
            assignment: Assignment object with type and value (e.g., {"type": "Fungible", "value": 42})
            recipient_id: Recipient ID (e.g., "bcrt:utxob:...")
            witness_data: Optional witness data with amount_sat and blinding
            donation: Whether this is a donation
            fee_rate: Fee rate for the transaction
            min_confirmations: Minimum confirmations required
            transport_endpoints: List of transport endpoints
            skip_sync: Whether to skip wallet sync
            
        Returns:
            str: Transaction ID (txid)
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "asset_id": asset_id,
            "assignment": assignment,
            "recipient_id": recipient_id,
            "donation": donation,
            "fee_rate": fee_rate,
            "min_confirmations": min_confirmations,
            "skip_sync": skip_sync
        }
        
        if witness_data is not None:
            payload["witness_data"] = witness_data
        
        if transport_endpoints is not None:
            payload["transport_endpoints"] = transport_endpoints
        
        logger.debug("Sending asset on RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/sendasset", timeout=60.0, json=payload)
        logger.debug(f"Send asset response: {data}")
        
        txid = data.get("txid")
        if not txid:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from RLN node: missing or empty 'txid' field"
            )
        return txid

    async def get_asset_balance(self, asset_id: str) -> Dict[str, Any]:
        """
        Get asset balance from the RLN node.
        
        Args:
            asset_id: Asset ID to get balance for
            
        Returns:
            Dict[str, Any]: Asset balance with settled, future, spendable, offchain_outbound, offchain_inbound
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "asset_id": asset_id
        }
        
        logger.debug("Getting asset balance from RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/assetbalance", timeout=30.0, json=payload)
        logger.debug(f"Asset balance response: {data}")
        return data

    async def close_channel(
        self,
        channel_id: str,
        peer_pubkey: str,
        force: bool = True
    ) -> Dict[str, Any]:
        """
        Close a Lightning channel.
        
        Args:
            channel_id: Channel ID to close
            peer_pubkey: Peer public key
            force: Whether to force close the channel
            
        Returns:
            Dict[str, Any]: Empty response dict
            
        Raises:
            HTTPException: If the request fails
        """
        payload = {
            "channel_id": channel_id,
            "peer_pubkey": peer_pubkey,
            "force": force
        }
        
        logger.debug("Closing channel on RLN node")
        logger.debug(f"Payload: {payload}")
        data = await self._make_request("POST", "/closechannel", timeout=60.0, json=payload)
        logger.debug(f"Close channel response: {data}")
        return data


# Global RLN client instance
_rln_client: Optional[RLNClient] = None


def get_rln_client() -> RLNClient:
    """Get or create the global RLN client instance."""
    global _rln_client
    if _rln_client is None:
        _rln_client = RLNClient()
    return _rln_client

