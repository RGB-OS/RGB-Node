"""
FastAPI client for refresh worker.

Handles HTTP communication with the FastAPI service.
"""
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional, List
from workers.config import API_URL, HTTP_TIMEOUT

logger = logging.getLogger(__name__)

# Global API client instance
_api_client: Optional['APIClient'] = None


class APIClient:
    """
    HTTP client for FastAPI service with retry logic.
    """
    
    def __init__(self, base_url: str, timeout: int = 60):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL of the FastAPI service
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def refresh_wallet(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call /wallet/refresh endpoint to sync wallet state.
        
        Args:
            job: Job dictionary with wallet credentials (xpub_van, xpub_col, master_fingerprint)
            
        Returns:
            Response from refresh endpoint
            
        Raises:
            ValueError: If job is missing required fields
            requests.exceptions.RequestException: If API call fails
        """
        required_fields = ['xpub_van', 'xpub_col', 'master_fingerprint']
        for field in required_fields:
            if field not in job:
                raise ValueError(f"Missing required field in job: {field}")
        
        headers = {
            'xpub-van': job['xpub_van'],
            'xpub-col': job['xpub_col'],
            'master-fingerprint': job['master_fingerprint']
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/wallet/refresh",
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout calling refresh API: {e}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error calling refresh API: {e.response.status_code} - {e.response.text}"
            )
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling refresh API: {e}")
            raise
    
    def list_assets(self, job: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        List all assets for a wallet.
        
        Args:
            job: Job dictionary with wallet credentials
            
        Returns:
            List of asset dictionaries (from nia, uda, cfa combined)
            
        Raises:
            requests.exceptions.RequestException: If API call fails
        """
        headers = {
            'xpub-van': job['xpub_van'],
            'xpub-col': job['xpub_col'],
            'master-fingerprint': job['master_fingerprint']
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/wallet/listassets",
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            
            # API returns GetAssetResponseModel with nia, uda, cfa fields
            assets = []
            if isinstance(result, dict):
                # Combine all asset types
                for asset_type in ['nia', 'uda', 'cfa']:
                    if asset_type in result and result[asset_type]:
                        type_assets = result[asset_type]
                        if isinstance(type_assets, list):
                            # Filter out None values
                            assets.extend([a for a in type_assets if a is not None])
            elif isinstance(result, list):
                # Fallback: if API returns list directly
                assets = result
            
            return assets
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling listassets API: {e}")
            raise
    
    def list_transfers(self, job: Dict[str, Any], asset_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List transfers for a specific asset or all transfers if asset_id is None.
        
        Args:
            job: Job dictionary with wallet credentials
            asset_id: Optional asset ID to list transfers for. If None, lists all transfers.
            
        Returns:
            List of transfer dictionaries
            
        Raises:
            requests.exceptions.RequestException: If API call fails
        """
        headers = {
            'xpub-van': job['xpub_van'],
            'xpub-col': job['xpub_col'],
            'master-fingerprint': job['master_fingerprint']
        }
        
        try:
            # Only include asset_id in request if it's not None
            request_body = {}
            if asset_id is not None:
                request_body['asset_id'] = asset_id
            
            response = self.session.post(
                f"{self.base_url}/wallet/listtransfers",
                headers=headers,
                json=request_body,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            
            # API returns ListTransferAssetResponseModel with 'transfers' field
            if isinstance(result, dict) and 'transfers' in result:
                transfers = result['transfers']
                if isinstance(transfers, list):
                    # Filter out None values
                    return [t for t in transfers if t is not None]
            elif isinstance(result, list):
                # Fallback: if API returns list directly
                return [t for t in result if t is not None]
            
            return []
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error calling listtransfers API for asset {asset_id}: {e}")
            return []
    
    def get_transfer_status(self, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get transfer status by calling /wallet/listtransfers.
        
        Args:
            job: Job dictionary with wallet credentials and transfer info (must have recipient_id)
            
        Returns:
            Transfer dictionary or None if not found
        """
        headers = {
            'xpub-van': job['xpub_van'],
            'xpub-col': job['xpub_col'],
            'master-fingerprint': job['master_fingerprint']
        }
        
        try:
            # Only include asset_id in request if it's not None
            request_body = {}
            asset_id = job.get('asset_id')
            if asset_id is not None:
                request_body['asset_id'] = asset_id
            
            response = self.session.post(
                f"{self.base_url}/wallet/listtransfers",
                headers=headers,
                json=request_body,
                timeout=self.timeout
            )
            response.raise_for_status()
            transfers = response.json()
            
            recipient_id = job.get('recipient_id')
            if not recipient_id:
                logger.warning("get_transfer_status called without recipient_id")
                return None
            
            # Find matching transfer by recipient_id
            for transfer in transfers:
                if transfer.get('recipient_id') == recipient_id:
                    return transfer
            
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error calling listtransfers API: {e}")
            return None
    
    def fail_transfers(self, job: Dict[str, Any], batch_transfer_idx: int, no_asset_only: bool = False, skip_sync: bool = False) -> Dict[str, Any]:
        """
        Call /wallet/failtransfers endpoint to fail expired transfers.
        
        Args:
            job: Job dictionary with wallet credentials (xpub_van, xpub_col, master_fingerprint)
            batch_transfer_idx: Batch transfer index to fail
            no_asset_only: If True, only fail transfers without assets
            skip_sync: If True, skip wallet sync
            
        Returns:
            Response from failtransfers endpoint
            
        Raises:
            ValueError: If job is missing required fields
            requests.exceptions.RequestException: If API call fails
        """
        required_fields = ['xpub_van', 'xpub_col', 'master_fingerprint']
        for field in required_fields:
            if field not in job:
                raise ValueError(f"Missing required field in job: {field}")
        
        headers = {
            'xpub-van': job['xpub_van'],
            'xpub-col': job['xpub_col'],
            'master-fingerprint': job['master_fingerprint']
        }
        
        payload = {
            'batch_transfer_idx': batch_transfer_idx,
            'no_asset_only': no_asset_only,
            'skip_sync': skip_sync
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/wallet/failtransfers",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout calling failtransfers API: {e}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error calling failtransfers API: {e.response.status_code} - {e.response.text}"
            )
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling failtransfers API: {e}")
            raise
    
    def health_check(self) -> bool:
        """
        Check if API is accessible.
        
        Returns:
            True if API is accessible, False otherwise
        """
        try:
            response = self.session.get(f"{self.base_url}/docs", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def close(self) -> None:
        """Close HTTP session."""
        self.session.close()


def get_api_client() -> APIClient:
    """
    Get or create global API client instance (singleton).
    
    Returns:
        APIClient instance
    """
    global _api_client
    if _api_client is None:
        _api_client = APIClient(API_URL, HTTP_TIMEOUT)
    return _api_client

